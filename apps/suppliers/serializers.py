from rest_framework import serializers
from .models import Supplier, SupplierProduct, PriceList
from apps.products.models import Product
from apps.products.serializers import ProductSerializer
from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer


class SupplierSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = Supplier
        fields = ('id', 'user', 'user_email', 'user_name', 'name', 'inn', 'kpp',
                  'ogrn', 'legal_address', 'actual_address', 'phone', 'email',
                  'is_active', 'created_at')
        read_only_fields = ('id', 'user', 'created_at')


class SupplierProductSerializer(serializers.ModelSerializer):
    product_details = ProductSerializer(source='product', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_article = serializers.CharField(source='product.article', read_only=True)

    class Meta:
        model = SupplierProduct
        fields = ('id', 'supplier', 'product', 'product_details', 'product_name',
                  'product_article', 'supplier_sku', 'price', 'quantity',
                  'is_available', 'updated_at')
        read_only_fields = ('id', 'supplier', 'updated_at')

    def validate(self, data):
        """Проверка уникальности товара для поставщика"""
        supplier = self.context['request'].user.supplier_profile
        product = data.get('product')

        if self.instance is None:
            if SupplierProduct.objects.filter(supplier=supplier, product=product).exists():
                raise serializers.ValidationError(
                    f"Товар {product.name} уже есть в вашем прайс-листе"
                )
        return data

    def create(self, validated_data):
        validated_data['supplier'] = self.context['request'].user.supplier_profile
        return super().create(validated_data)


class PriceListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)

    class Meta:
        model = PriceList
        fields = ('id', 'supplier', 'supplier_name', 'file', 'uploaded_at',
                  'processed_at', 'is_processed', 'error_message')
        read_only_fields = ('id', 'supplier', 'uploaded_at', 'processed_at',
                            'is_processed', 'error_message')


class SupplierOrderItemSerializer(serializers.Serializer):
    """Сериализатор для позиций заказа поставщика"""
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_article = serializers.CharField()
    quantity = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    total = serializers.DecimalField(max_digits=10, decimal_places=2)


class SupplierOrderSerializer(serializers.ModelSerializer):
    """Сериализатор заказа для поставщика"""
    customer_name = serializers.CharField(source='user.get_full_name', read_only=True)
    customer_email = serializers.EmailField(source='user.email', read_only=True)
    customer_phone = serializers.CharField(source='user.phone', read_only=True)
    delivery_address = serializers.CharField(source='contact.full_address', read_only=True)
    supplier_items = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ('id', 'customer_name', 'customer_email', 'customer_phone',
                  'delivery_address', 'status', 'created_at', 'supplier_items',
                  'total_price')
        read_only_fields = ('id', 'created_at', 'total_price')

    def get_supplier_items(self, obj):
        """Получение только товаров данного поставщика"""
        supplier = self.context['request'].user.supplier_profile
        items = obj.items.filter(
            product__supplier_products__supplier=supplier
        ).select_related('product')

        result = []
        for item in items:
            result.append({
                'product_id': item.product.id,
                'product_name': item.product.name,
                'product_article': item.product.article,
                'quantity': item.quantity,
                'price': float(item.price),
                'total': float(item.total_price)
            })
        return result