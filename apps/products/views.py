from rest_framework import generics, filters, permissions, status
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.db import IntegrityError, DataError, DatabaseError
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.files.uploadedfile import UploadedFile
import yaml
import csv
import io
import logging
from yaml.scanner import ScannerError
from yaml.parser import ParserError

from .models import Category, Product, ProductParameter
from .serializers import CategorySerializer, ProductSerializer, ProductImportSerializer
from apps.suppliers.models import SupplierProduct

logger = logging.getLogger(__name__)


class CategoryListView(generics.ListAPIView):
    """Список категорий"""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except DatabaseError as e:
            logger.error(f"Database error listing categories: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductListView(generics.ListAPIView):
    """Список товаров с фильтрацией и поиском"""
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'supplier_products__supplier']
    search_fields = ['name', 'description', 'article']
    ordering_fields = ['price', 'name', 'created_at']

    def get_queryset(self):
        try:
            queryset = Product.objects.filter(quantity__gt=0)
            min_price = self.request.query_params.get('min_price')
            max_price = self.request.query_params.get('max_price')

            if min_price:
                try:
                    min_price = float(min_price)
                    if min_price < 0:
                        return Response(
                            {'error': 'Минимальная цена не может быть отрицательной'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    queryset = queryset.filter(price__gte=min_price)
                except ValueError:
                    return Response(
                        {'error': 'Некорректный формат минимальной цены'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            if max_price:
                try:
                    max_price = float(max_price)
                    if max_price < 0:
                        return Response(
                            {'error': 'Максимальная цена не может быть отрицательной'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    queryset = queryset.filter(price__lte=max_price)
                except ValueError:
                    return Response(
                        {'error': 'Некорректный формат максимальной цены'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            return queryset
        except DatabaseError as e:
            logger.error(f"Database error in product list: {e}")
            return Product.objects.none()

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except DatabaseError as e:
            logger.error(f"Database error listing products: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductDetailView(generics.RetrieveAPIView):
    """Детальная информация о товаре"""
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def retrieve(self, request, *args, **kwargs):
        try:
            return super().retrieve(request, *args, **kwargs)
        except ObjectDoesNotExist:
            return Response(
                {'error': 'Товар не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
        except DatabaseError as e:
            logger.error(f"Database error retrieving product: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductImportView(generics.CreateAPIView):
    """Импорт товаров из YAML/CSV файла"""
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
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

            if not isinstance(file, UploadedFile):
                return Response(
                    {'error': 'Некорректный формат файла'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            allowed_extensions = ['.yaml', '.yml', '.csv']
            file_extension = file.name.lower()
            if not any(file_extension.endswith(ext) for ext in allowed_extensions):
                return Response(
                    {'error': 'Поддерживаются только файлы с расширением .yaml, .yml или .csv'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if file.size > 10 * 1024 * 1024:
                return Response(
                    {'error': 'Файл слишком большой. Максимальный размер 10MB'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            file_format = request.data.get('format', 'yaml')

            try:
                if file_format == 'yaml':
                    try:
                        data = yaml.safe_load(file.read())
                        if data is None:
                            return Response(
                                {'error': 'Пустой YAML файл'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                        if not isinstance(data, list):
                            return Response(
                                {'error': 'YAML файл должен содержать список товаров'},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                    except (ScannerError, ParserError) as e:
                        return Response(
                            {'error': f'Ошибка парсинга YAML: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                elif file_format == 'csv':
                    try:
                        data = self._parse_csv(file)
                    except csv.Error as e:
                        return Response(
                            {'error': f'Ошибка парсинга CSV: {str(e)}'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                else:
                    return Response(
                        {'error': 'Поддерживаются только YAML и CSV форматы'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if not data:
                    return Response(
                        {'error': 'Файл не содержит данных'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                try:
                    if not hasattr(request.user, 'supplier_profile'):
                        return Response(
                            {'error': 'У вас нет профиля поставщика'},
                            status=status.HTTP_403_FORBIDDEN
                        )

                    result = self._import_products(data, request.user.supplier_profile)
                    return Response(result, status=status.HTTP_200_OK)
                except IntegrityError as e:
                    logger.error(f"Integrity error during import: {e}")
                    return Response(
                        {'error': 'Ошибка целостности данных. Проверьте уникальность артикулов.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                except DataError as e:
                    return Response(
                        {'error': f'Ошибка формата данных: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                except ValidationError as e:
                    return Response(
                        {'error': str(e)},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            except UnicodeDecodeError as e:
                return Response(
                    {'error': 'Ошибка кодировки файла. Используйте UTF-8.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.exception(f"Unexpected error during import: {e}")
            return Response(
                {'error': 'Внутренняя ошибка сервера'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _parse_csv(self, file):
        """Парсинг CSV файла с валидацией"""
        try:
            decoded_file = file.read().decode('utf-8')
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string)
            required_columns = ['category', 'name', 'article', 'price']
            if not reader.fieldnames:
                raise csv.Error("CSV файл не содержит заголовков")

            missing_columns = [col for col in required_columns if col not in reader.fieldnames]
            if missing_columns:
                raise csv.Error(f"Отсутствуют обязательные колонки: {', '.join(missing_columns)}")

            data = list(reader)
            if len(data) > 1000:
                raise csv.Error("Слишком много строк в CSV файле. Максимум 1000.")

            return data
        except UnicodeDecodeError:
            raise UnicodeDecodeError("Файл должен быть в кодировке UTF-8")

    def _import_products(self, data, supplier):
        """Импорт товаров в БД с валидацией"""
        imported = 0
        updated = 0
        errors = []

        for idx, item in enumerate(data, start=1):
            try:
                required_fields = ['category', 'name', 'article', 'price']
                for field in required_fields:
                    if field not in item or not item[field]:
                        raise ValidationError(f"Строка {idx}: отсутствует обязательное поле '{field}'")

                try:
                    price = float(item['price'])
                    if price <= 0:
                        raise ValidationError(f"Строка {idx}: цена должна быть положительным числом")
                except ValueError:
                    raise ValidationError(f"Строка {idx}: некорректный формат цены")
                quantity = 0
                if 'quantity' in item and item['quantity']:
                    try:
                        quantity = int(item['quantity'])
                        if quantity < 0:
                            raise ValidationError(f"Строка {idx}: количество не может быть отрицательным")
                    except ValueError:
                        raise ValidationError(f"Строка {idx}: некорректный формат количества")

                serializer = ProductImportSerializer(data=item)
                if serializer.is_valid():
                    category_name = serializer.validated_data['category'].strip()
                    category, _ = Category.objects.get_or_create(
                        name=category_name,
                        defaults={'slug': category_name.lower().replace(' ', '-')}
                    )

                    product, created = Product.objects.update_or_create(
                        article=serializer.validated_data['article'].strip(),
                        defaults={
                            'category': category,
                            'name': serializer.validated_data['name'].strip(),
                            'price': price,
                            'quantity': quantity,
                            'description': serializer.validated_data.get('description', '').strip()
                        }
                    )

                    SupplierProduct.objects.update_or_create(
                        supplier=supplier,
                        product=product,
                        defaults={
                            'supplier_sku': serializer.validated_data['article'].strip(),
                            'price': price,
                            'quantity': quantity,
                            'is_available': quantity > 0
                        }
                    )

                    if 'parameters' in serializer.validated_data and serializer.validated_data['parameters']:
                        parameters = serializer.validated_data['parameters']
                        if isinstance(parameters, dict):
                            for param_name, param_value in parameters.items():
                                if param_value:
                                    ProductParameter.objects.update_or_create(
                                        product=product,
                                        name=param_name.strip(),
                                        defaults={'value': str(param_value).strip()}
                                    )

                    if created:
                        imported += 1
                    else:
                        updated += 1

                else:
                    errors.append(f"Строка {idx}: ошибка валидации - {serializer.errors}")

            except ValidationError as e:
                errors.append(str(e))
            except IntegrityError as e:
                errors.append(f"Строка {idx}: ошибка целостности данных - {str(e)}")
            except Exception as e:
                errors.append(f"Строка {idx}: непредвиденная ошибка - {str(e)}")

        return {
            'success': True,
            'imported': imported,
            'updated': updated,
            'errors': errors,
            'total': len(data)
        }