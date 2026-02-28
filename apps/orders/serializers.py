from rest_framework import serializers
from .models import Order, OrderItem
from apps.products.serializers import ProductSerializer
from apps.accounts.serializers import ContactSerializer


class OrderItemSerializer(serializers.ModelSerializer):
    product_details = ProductSerializer(source='product', read_only=True)

    class Meta:
        model = OrderItem
        fields = ('id', 'product', 'product_details', 'quantity', 'price', 'total_price')
        read_only_fields = ('id', 'price', 'total_price')


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    contact_details = ContactSerializer(source='contact', read_only=True)

    class Meta:
        model = Order
        fields = ('id', 'user', 'contact', 'contact_details', 'status',
                  'items', 'total_price', 'created_at', 'updated_at')
        read_only_fields = ('id', 'user', 'created_at', 'updated_at', 'total_price')


class OrderCreateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(child=serializers.DictField(), write_only=True)

    class Meta:
        model = Order
        fields = ('id', 'contact', 'items', 'status')
        read_only_fields = ('id',)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Корзина не может быть пустой")

        for item in value:
            if not all(k in item for k in ('product_id', 'quantity')):
                raise serializers.ValidationError(
                    "Каждый элемент должен содержать product_id и quantity"
                )
        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        validated_data['user'] = self.context['request'].user
        validated_data['status'] = 'new'

        order = Order.objects.create(**validated_data)

        for item_data in items_data:
            product_id = item_data['product_id']
            quantity = item_data['quantity']

            from apps.products.models import Product
            product = Product.objects.get(id=product_id)

            OrderItem.objects.create(
                order=order,
                product_id=product_id,
                quantity=quantity,
                price=product.price
            )

        return order