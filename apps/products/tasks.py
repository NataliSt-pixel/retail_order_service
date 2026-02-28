from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import yaml
import csv
import io

from .models import Product, Category, ProductParameter
from apps.suppliers.models import SupplierProduct, Supplier


@shared_task
def send_email_task(subject, message, recipient_list):
    """Асинхронная отправка email"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        recipient_list,
        fail_silently=True,
    )
    return f"Email отправлен на {', '.join(recipient_list)}"


@shared_task
def import_products_task(file_content, file_format, supplier_id):
    """Асинхронный импорт товаров"""
    from apps.products.models import Product, Category, ProductParameter
    from apps.suppliers.models import Supplier, SupplierProduct

    supplier = Supplier.objects.get(id=supplier_id)

    try:
        if file_format == 'yaml':
            data = yaml.safe_load(file_content)
        elif file_format == 'csv':
            decoded_file = file_content.decode('utf-8')
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string)
            data = list(reader)
        else:
            return {"error": "Неподдерживаемый формат файла"}

        imported = 0
        updated = 0
        errors = []

        for item in data:
            try:
                category, _ = Category.objects.get_or_create(
                    name=item.get('category', 'Без категории')
                )

                product, created = Product.objects.update_or_create(
                    article=item['article'],
                    defaults={
                        'category': category,
                        'name': item['name'],
                        'price': float(item['price']),
                        'quantity': int(item.get('quantity', 0)),
                        'description': item.get('description', '')
                    }
                )

                SupplierProduct.objects.update_or_create(
                    supplier=supplier,
                    product=product,
                    defaults={
                        'supplier_sku': item['article'],
                        'price': float(item['price']),
                        'quantity': int(item.get('quantity', 0))
                    }
                )

                if created:
                    imported += 1
                else:
                    updated += 1

            except Exception as e:
                errors.append(f"Ошибка при импорте {item.get('article', 'unknown')}: {str(e)}")

        return {
            'success': True,
            'imported': imported,
            'updated': updated,
            'errors': errors
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }