from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.core.mail import send_mail, BadHeaderError
from django.conf import settings
from django.db import transaction, DatabaseError, IntegrityError
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.shortcuts import get_object_or_404
import logging

from .models import Order, OrderItem
from .serializers import OrderSerializer, OrderCreateSerializer
from apps.products.models import Product
from apps.accounts.models import Contact

logger = logging.getLogger(__name__)


class BasketView(generics.RetrieveUpdateAPIView):
    """Работа с корзиной пользователя"""
    serializer_class = OrderSerializer

    def get_object(self):
        try:
            basket, created = Order.objects.get_or_create(
                user=self.request.user,
                status='basket'
            )
            return basket
        except DatabaseError as e:
            logger.error(f"Database error getting basket: {e}")
            raise ValidationError("Ошибка получения корзины")

    def update(self, request, *args, **kwargs):
        try:
            basket = self.get_object()
            action = request.data.get('action')

            if not action:
                return Response(
                    {'error': 'Не указано действие'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if action == 'add':
                return self.add_to_basket(request, basket)
            elif action == 'remove':
                return self.remove_from_basket(request, basket)
            elif action == 'clear':
                return self.clear_basket(basket)
            elif action == 'update_quantity':
                return self.update_quantity(request, basket)
            else:
                return Response(
                    {'error': f'Неверное действие: {action}. Допустимые: add, remove, clear, update_quantity'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except ValidationError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception(f"Unexpected error in basket: {e}")
            return Response(
                {'error': 'Внутренняя ошибка сервера'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def add_to_basket(self, request, basket):
        """Добавление товара в корзину"""
        try:
            product_id = request.data.get('product_id')
            if not product_id:
                return Response(
                    {'error': 'Не указан ID товара'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                product_id = int(product_id)
            except ValueError:
                return Response(
                    {'error': 'ID товара должен быть числом'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                quantity = int(request.data.get('quantity', 1))
                if quantity <= 0:
                    return Response(
                        {'error': 'Количество должно быть положительным числом'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                if quantity > 999:
                    return Response(
                        {'error': 'Слишком большое количество. Максимум 999'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except ValueError:
                return Response(
                    {'error': 'Количество должно быть числом'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                product = Product.objects.get(id=product_id)
            except ObjectDoesNotExist:
                return Response(
                    {'error': 'Товар не найден'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if product.quantity < quantity:
                return Response(
                    {'error': f'Доступно только {product.quantity} ед. товара "{product.name}"'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            with transaction.atomic():
                item = basket.items.select_for_update().filter(product_id=product_id).first()

                if item:
                    new_quantity = item.quantity + quantity
                    if new_quantity > 999:
                        return Response(
                            {'error': 'Слишком большое количество в корзине. Максимум 999'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    if product.quantity >= new_quantity:
                        item.quantity = new_quantity
                        item.save()
                    else:
                        return Response(
                            {'error': f'Всего доступно {product.quantity} ед., в корзине уже {item.quantity}'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                else:
                    OrderItem.objects.create(
                        order=basket,
                        product=product,
                        quantity=quantity,
                        price=product.price
                    )

            serializer = self.get_serializer(basket)
            return Response(serializer.data)

        except IntegrityError as e:
            logger.error(f"Integrity error adding to basket: {e}")
            return Response(
                {'error': 'Ошибка при добавлении в корзину'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except DatabaseError as e:
            logger.error(f"Database error in basket: {e}")
            return Response(
                {'error': 'Ошибка базы данных. Попробуйте позже.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def remove_from_basket(self, request, basket):
        """Удаление товара из корзины"""
        try:
            item_id = request.data.get('item_id')
            if not item_id:
                return Response(
                    {'error': 'Не указан ID позиции'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                item_id = int(item_id)
            except ValueError:
                return Response(
                    {'error': 'ID позиции должен быть числом'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                item = basket.items.get(id=item_id)
                item.delete()
            except ObjectDoesNotExist:
                return Response(
                    {'error': 'Позиция не найдена в корзине'},
                    status=status.HTTP_404_NOT_FOUND
                )

            serializer = self.get_serializer(basket)
            return Response(serializer.data)

        except DatabaseError as e:
            logger.error(f"Database error removing from basket: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def clear_basket(self, basket):
        """Очистка корзины"""
        try:
            basket.items.all().delete()
            serializer = self.get_serializer(basket)
            return Response(serializer.data)
        except DatabaseError as e:
            logger.error(f"Database error clearing basket: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def update_quantity(self, request, basket):
        """Обновление количества товара"""
        try:
            item_id = request.data.get('item_id')
            quantity = request.data.get('quantity')

            if not item_id or quantity is None:
                return Response(
                    {'error': 'Не указаны ID позиции или количество'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                item_id = int(item_id)
            except ValueError:
                return Response(
                    {'error': 'ID позиции должен быть числом'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                quantity = int(quantity)
                if quantity < 0:
                    return Response(
                        {'error': 'Количество не может быть отрицательным'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                if quantity > 999:
                    return Response(
                        {'error': 'Слишком большое количество. Максимум 999'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except ValueError:
                return Response(
                    {'error': 'Количество должно быть числом'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                item = basket.items.select_related('product').get(id=item_id)
            except ObjectDoesNotExist:
                return Response(
                    {'error': 'Позиция не найдена в корзине'},
                    status=status.HTTP_404_NOT_FOUND
                )

            if quantity == 0:
                item.delete()
            else:
                if item.product.quantity >= quantity:
                    item.quantity = quantity
                    item.save()
                else:
                    return Response(
                        {'error': f'Доступно только {item.product.quantity} ед. товара "{item.product.name}"'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            serializer = self.get_serializer(basket)
            return Response(serializer.data)

        except DatabaseError as e:
            logger.error(f"Database error updating quantity: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OrderListView(generics.ListAPIView):
    """Список заказов пользователя"""
    serializer_class = OrderSerializer

    def get_queryset(self):
        try:
            return Order.objects.filter(
                user=self.request.user
            ).exclude(status='basket').order_by('-created_at')
        except DatabaseError as e:
            logger.error(f"Database error listing orders: {e}")
            return Order.objects.none()

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except DatabaseError as e:
            logger.error(f"Database error in order list: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OrderDetailView(generics.RetrieveAPIView):
    """Детали заказа"""
    serializer_class = OrderSerializer

    def get_queryset(self):
        try:
            return Order.objects.filter(user=self.request.user)
        except DatabaseError as e:
            logger.error(f"Database error getting order detail: {e}")
            return Order.objects.none()

    def retrieve(self, request, *args, **kwargs):
        try:
            return super().retrieve(request, *args, **kwargs)
        except ObjectDoesNotExist:
            return Response(
                {'error': 'Заказ не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
        except DatabaseError as e:
            logger.error(f"Database error retrieving order: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OrderConfirmView(generics.UpdateAPIView):
    """Подтверждение заказа"""
    serializer_class = OrderSerializer
    queryset = Order.objects.all()

    def update(self, request, *args, **kwargs):
        try:
            order = self.get_object()

            if order.status != 'basket':
                return Response(
                    {'error': 'Заказ уже оформлен'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            contact_id = request.data.get('contact_id')
            if not contact_id:
                return Response(
                    {'error': 'Необходимо указать контакт для доставки'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                contact_id = int(contact_id)
            except ValueError:
                return Response(
                    {'error': 'ID контакта должен быть числом'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                contact = Contact.objects.get(id=contact_id, user=request.user)
            except ObjectDoesNotExist:
                return Response(
                    {'error': 'Контакт не найден'},
                    status=status.HTTP_404_NOT_FOUND
                )

            for item in order.items.select_related('product').all():
                if item.product.quantity < item.quantity:
                    return Response(
                        {'error': f'Товар "{item.product.name}" доступен в количестве {item.product.quantity}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            with transaction.atomic():
                order.contact = contact
                order.status = 'new'
                order.save()

                for item in order.items.select_related('product').all():
                    product = item.product
                    product.quantity -= item.quantity
                    product.save()

            try:
                self._send_confirmation_email(order)
            except (BadHeaderError, ConnectionError) as e:
                logger.error(f"Error sending confirmation email: {e}")
            try:
                self._send_admin_notification(order)
            except (BadHeaderError, ConnectionError) as e:
                logger.error(f"Error sending admin notification: {e}")

            serializer = self.get_serializer(order)
            return Response(serializer.data)

        except IntegrityError as e:
            logger.error(f"Integrity error confirming order: {e}")
            return Response(
                {'error': 'Ошибка при подтверждении заказа'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except DatabaseError as e:
            logger.error(f"Database error confirming order: {e}")
            return Response(
                {'error': 'Ошибка базы данных'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.exception(f"Unexpected error confirming order: {e}")
            return Response(
                {'error': 'Внутренняя ошибка сервера'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _send_confirmation_email(self, order):
        """Отправка подтверждения клиенту"""
        try:
            subject = f'Подтверждение заказа #{order.id}'
            message = f'''
            Здравствуйте, {order.user.first_name or order.user.email}!

            Ваш заказ #{order.id} успешно оформлен.

            Состав заказа:
            {self._format_order_items(order)}

            Сумма заказа: {order.total_price} руб.
            Адрес доставки: {order.contact.full_address if order.contact else 'Не указан'}

            Статус заказа вы можете отслеживать в личном кабинете.

            Спасибо за покупку!
            '''

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [order.user.email],
                fail_silently=False,
            )
        except BadHeaderError:
            raise
        except Exception as e:
            logger.error(f"Failed to send confirmation email: {e}")
            raise

    def _send_admin_notification(self, order):
        """Отправка уведомления администратору"""
        try:
            subject = f'Новый заказ #{order.id}'
            message = f'''
            Поступил новый заказ #{order.id}

            Покупатель: {order.user.email} ({order.user.get_full_name() or 'Имя не указано'})
            Телефон: {order.user.phone or 'Не указан'}

            Состав заказа:
            {self._format_order_items(order)}

            Сумма заказа: {order.total_price} руб.
            Адрес доставки: {order.contact.full_address if order.contact else 'Не указан'}
            '''

            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [settings.ADMIN_EMAIL],
                fail_silently=False,
            )
        except BadHeaderError:
            raise
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")
            raise

    def _format_order_items(self, order):
        """Форматирование списка товаров"""
        items_text = ""
        for item in order.items.select_related('product').all():
            items_text += f"\n- {item.product.name} x{item.quantity} = {item.total_price} руб."
        return items_text