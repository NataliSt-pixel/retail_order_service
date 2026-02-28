from rest_framework import serializers
from .models import Category, Product, ProductParameter


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name', 'slug', 'parent')
        read_only_fields = ('id',)


class ProductParameterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductParameter
        fields = ('id', 'name', 'value')


class ProductSerializer(serializers.ModelSerializer):
    parameters = ProductParameterSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = ('id', 'category', 'category_name', 'name', 'slug',
                  'description', 'image', 'article', 'price', 'quantity',
                  'parameters', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class ProductImportSerializer(serializers.Serializer):
    """Сериализатор для импорта товаров"""
    category = serializers.CharField()
    name = serializers.CharField()
    article = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    quantity = serializers.IntegerField()
    description = serializers.CharField(required=False, allow_blank=True)
    parameters = serializers.DictField(child=serializers.CharField(), required=False)