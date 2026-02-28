from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Order, OrderItem
from .serializers import OrderSerializer, OrderCreateSerializer
from apps.products.models import Product


class BasketView(generics.RetrieveUpdateAPIView):
    """Работа с корзиной пользователя"""
    serializer_class = OrderSerializer

    def get_object(self):
        basket, _ = Order.objects.get_or_create(
            user=self.request.user,
            status='basket'
        )
        return basket

    def update(self, request, *args, **kwargs):
        basket = self.get_object()
        action = request.data.get('action')

        if action == 'add':
            return self.add_to_basket(request, basket)
        elif action == 'remove':
            return self.remove_from_basket(request, basket)
        elif action == 'clear':
            return self.clear_basket(basket)
        elif action == 'update_quantity':
            return self.update_quantity(request, basket)

        return Response(
            {'error': 'Неверное действие'},
            status=status.HTTP_400_BAD_REQUEST
        )

    def add_to_basket(self, request, basket):
        """Добавление товара в корзину"""
        product_id = request.data.get('product_id')
        quantity = int(request.data.get('quantity', 1))

        product = get_object_or_404(Product, id=product_id)

        if product.quantity < quantity:
            return Response(
                {'error': f'Доступно только {product.quantity} ед.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        item = basket.items.filter(product_id=product_id).first()
        if item:
            new_quantity = item.quantity + quantity
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

    def remove_from_basket(self, request, basket):
        """Удаление товара из корзины"""
        item_id = request.data.get('item_id')
        item = get_object_or_404(basket.items, id=item_id)
        item.delete()

        serializer = self.get_serializer(basket)
        return Response(serializer.data)

    def clear_basket(self, basket):
        """Очистка корзины"""
        basket.items.all().delete()
        serializer = self.get_serializer(basket)
        return Response(serializer.data)

    def update_quantity(self, request, basket):
        """Обновление количества товара"""
        item_id = request.data.get('item_id')
        quantity = int(request.data.get('quantity'))

        item = get_object_or_404(basket.items, id=item_id)

        if quantity <= 0:
            item.delete()
        else:
            if item.product.quantity >= quantity:
                item.quantity = quantity
                item.save()
            else:
                return Response(
                    {'error': f'Доступно только {item.product.quantity} ед.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = self.get_serializer(basket)
        return Response(serializer.data)


class OrderListView(generics.ListAPIView):
    """Список заказов пользователя"""
    serializer_class = OrderSerializer

    def get_queryset(self):
        return Order.objects.filter(
            user=self.request.user
        ).exclude(status='basket').order_by('-created_at')


class OrderDetailView(generics.RetrieveAPIView):
    """Детали заказа"""
    serializer_class = OrderSerializer

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)


class OrderConfirmView(generics.UpdateAPIView):
    """Подтверждение заказа"""
    serializer_class = OrderSerializer
    queryset = Order.objects.all()

    def update(self, request, *args, **kwargs):
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

        from apps.accounts.models import Contact
        contact = get_object_or_404(Contact, id=contact_id, user=request.user)
        for item in order.items.all():
            if item.product.quantity < item.quantity:
                return Response(
                    {'error': f'Товар {item.product.name} доступен в количестве {item.product.quantity}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        order.contact = contact
        order.status = 'new'
        order.save()

        self._send_confirmation_email(order)
        self._send_admin_notification(order)

        serializer = self.get_serializer(order)
        return Response(serializer.data)

    def _send_confirmation_email(self, order):
        """Отправка подтверждения клиенту"""
        subject = f'Подтверждение заказа #{order.id}'
        message = f'''
        Здравствуйте, {order.user.first_name}!

        Ваш заказ #{order.id} успешно оформлен.

        Состав заказа:
        {self._format_order_items(order)}

        Сумма заказа: {order.total_price} руб.
        Адрес доставки: {order.contact.full_address}

        Статус заказа вы можете отслеживать в личном кабинете.

        Спасибо за покупку!
        '''

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [order.user.email],
            fail_silently=True,
        )

    def _send_admin_notification(self, order):
        """Отправка уведомления администратору"""
        subject = f'Новый заказ #{order.id}'
        message = f'''
        Поступил новый заказ #{order.id}

        Покупатель: {order.user.email} ({order.user.get_full_name()})
        Телефон: {order.user.phone}

        Состав заказа:
        {self._format_order_items(order)}

        Сумма заказа: {order.total_price} руб.
        Адрес доставки: {order.contact.full_address}
        '''

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_EMAIL],
            fail_silently=True,
        )

    def _format_order_items(self, order):
        """Форматирование списка товаров"""
        items_text = ""
        for item in order.items.all():
            items_text += f"\n- {item.product.name} x{item.quantity} = {item.total_price} руб."
        return items_text