from django.db import models
from django.core.validators import MinValueValidator
from apps.accounts.models import User


class Supplier(models.Model):
    """Поставщик"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='supplier_profile')
    name = models.CharField(max_length=200, verbose_name='Название компании')
    inn = models.CharField(max_length=12, unique=True, verbose_name='ИНН')
    kpp = models.CharField(max_length=9, blank=True, verbose_name='КПП')
    ogrn = models.CharField(max_length=15, blank=True, verbose_name='ОГРН')
    legal_address = models.TextField(verbose_name='Юридический адрес')
    actual_address = models.TextField(verbose_name='Фактический адрес')
    phone = models.CharField(max_length=20, verbose_name='Телефон')
    email = models.EmailField(verbose_name='Email')
    is_active = models.BooleanField(default=True, verbose_name='Принимает заказы')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Поставщик'
        verbose_name_plural = 'Поставщики'

    def __str__(self):
        return self.name


class SupplierProduct(models.Model):
    """Товар поставщика"""
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='products')
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='supplier_products')
    supplier_sku = models.CharField(max_length=100, verbose_name='Артикул поставщика')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена поставщика')
    quantity = models.PositiveIntegerField(default=0, verbose_name='Количество у поставщика')
    is_available = models.BooleanField(default=True, verbose_name='Доступен к заказу')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Товар поставщика'
        verbose_name_plural = 'Товары поставщиков'
        unique_together = ['supplier', 'product']

    def __str__(self):
        return f"{self.supplier.name} - {self.product.name}"


class PriceList(models.Model):
    """Прайс-лист поставщика"""
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='price_lists')
    file = models.FileField(upload_to='price_lists/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    is_processed = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Прайс-лист'
        verbose_name_plural = 'Прайс-листы'

    def __str__(self):
        return f"Прайс-лист {self.supplier.name} от {self.uploaded_at.date()}"