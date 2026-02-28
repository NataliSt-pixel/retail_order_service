from rest_framework import generics, filters, permissions, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
import yaml
import csv
import io

from .models import Category, Product, ProductParameter
from .serializers import CategorySerializer, ProductSerializer, ProductImportSerializer
from apps.suppliers.models import SupplierProduct


class CategoryListView(generics.ListAPIView):
    """Список категорий"""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']


class ProductListView(generics.ListAPIView):
    """Список товаров с фильтрацией и поиском"""
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'supplier_products__supplier']
    search_fields = ['name', 'description', 'article']
    ordering_fields = ['price', 'name', 'created_at']

    def get_queryset(self):
        queryset = Product.objects.filter(quantity__gt=0)
        min_price = self.request.query_params.get('min_price')
        max_price = self.request.query_params.get('max_price')
        if min_price:
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            queryset = queryset.filter(price__lte=max_price)

        return queryset


class ProductDetailView(generics.RetrieveAPIView):
    """Детальная информация о товаре"""
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'


class ProductImportView(generics.CreateAPIView):
    """Импорт товаров из YAML/CSV файла"""
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not request.user.is_supplier:
            return Response(
                {'error': 'Только поставщики могут импортировать товары'},
                status=status.HTTP_403_FORBIDDEN
            )

        file = request.FILES.get('file')
        if not file:
            return Response(
                {'error': 'Необходимо загрузить файл'},
                status=status.HTTP_400_BAD_REQUEST
            )

        file_format = request.data.get('format', 'yaml')

        try:
            if file_format == 'yaml':
                data = yaml.safe_load(file.read())
            elif file_format == 'csv':
                data = self._parse_csv(file)
            else:
                return Response(
                    {'error': 'Поддерживаются только YAML и CSV форматы'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            result = self._import_products(data, request.user.supplier_profile)
            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _parse_csv(self, file):
        """Парсинг CSV файла"""
        decoded_file = file.read().decode('utf-8')
        io_string = io.StringIO(decoded_file)
        reader = csv.DictReader(io_string)
        return list(reader)

    def _import_products(self, data, supplier):
        """Импорт товаров в БД"""
        imported = 0
        updated = 0
        errors = []

        for item in data:
            serializer = ProductImportSerializer(data=item)
            if serializer.is_valid():
                try:
                    category, _ = Category.objects.get_or_create(
                        name=serializer.validated_data['category']
                    )

                    product, created = Product.objects.update_or_create(
                        article=serializer.validated_data['article'],
                        defaults={
                            'category': category,
                            'name': serializer.validated_data['name'],
                            'price': serializer.validated_data['price'],
                            'quantity': serializer.validated_data['quantity'],
                            'description': serializer.validated_data.get('description', '')
                        }
                    )

                    SupplierProduct.objects.update_or_create(
                        supplier=supplier,
                        product=product,
                        defaults={
                            'supplier_sku': serializer.validated_data['article'],
                            'price': serializer.validated_data['price'],
                            'quantity': serializer.validated_data['quantity']
                        }
                    )

                    if 'parameters' in serializer.validated_data:
                        for param_name, param_value in serializer.validated_data['parameters'].items():
                            ProductParameter.objects.update_or_create(
                                product=product,
                                name=param_name,
                                defaults={'value': param_value}
                            )

                    if created:
                        imported += 1
                    else:
                        updated += 1

                except Exception as e:
                    errors.append(f"Ошибка при импорте {item.get('article', 'unknown')}: {str(e)}")
            else:
                errors.append(f"Ошибка валидации: {serializer.errors}")

        return {
            'imported': imported,
            'updated': updated,
            'errors': errors
        }