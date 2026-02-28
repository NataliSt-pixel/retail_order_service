from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404

from .models import Supplier, SupplierProduct, PriceList
from apps.orders.models import Order, OrderItem
from .serializers import (
    SupplierSerializer, SupplierProductSerializer,
    PriceListSerializer, SupplierOrderSerializer
)
from apps.products.tasks import import_products_task


class SupplierProfileView(generics.RetrieveUpdateAPIView):
    """Профиль поставщика"""
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        if not hasattr(self.request.user, 'supplier_profile'):
            supplier = Supplier.objects.create(
                user=self.request.user,
                name=self.request.user.company or f"Поставщик {self.request.user.email}",
                email=self.request.user.email,
                phone=self.request.user.phone or '',
                legal_address='',
                actual_address='',
                inn='',
            )
            return supplier
        return self.request.user.supplier_profile


class SupplierProductListView(generics.ListCreateAPIView):
    """Список товаров поставщика"""
    serializer_class = SupplierProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'supplier_profile'):
            return SupplierProduct.objects.none()
        return SupplierProduct.objects.filter(supplier__user=self.request.user)

    def perform_create(self, serializer):
        if not hasattr(self.request.user, 'supplier_profile'):
            raise serializers.ValidationError("Сначала создайте профиль поставщика")
        serializer.save(supplier=self.request.user.supplier_profile)


class SupplierProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Детали товара поставщика"""
    serializer_class = SupplierProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'supplier_profile'):
            return SupplierProduct.objects.none()
        return SupplierProduct.objects.filter(supplier__user=self.request.user)


class SupplierOrderListView(generics.ListAPIView):
    """Список заказов для поставщика"""
    serializer_class = SupplierOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'supplier_profile'):
            return Order.objects.none()
        supplier = self.request.user.supplier_profile
        return Order.objects.filter(
            items__product__supplier_products__supplier=supplier
        ).exclude(status='basket').distinct().order_by('-created_at')


class SupplierOrderDetailView(generics.RetrieveUpdateAPIView):
    """Детали заказа для поставщика"""
    serializer_class = SupplierOrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not hasattr(self.request.user, 'supplier_profile'):
            return Order.objects.none()
        supplier = self.request.user.supplier_profile
        return Order.objects.filter(
            items__product__supplier_products__supplier=supplier
        ).exclude(status='basket').distinct()

    def perform_update(self, serializer):
        order = serializer.save()

        pass


class ToggleOrderReceivingView(generics.UpdateAPIView):
    """Включение/отключение приема заказов"""
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        if not hasattr(self.request.user, 'supplier_profile'):
            raise serializers.ValidationError("Сначала создайте профиль поставщика")
        return self.request.user.supplier_profile

    def update(self, request, *args, **kwargs):
        supplier = self.get_object()
        supplier.is_active = not supplier.is_active
        supplier.save()

        status_text = "включен" if supplier.is_active else "отключен"
        return Response({
            'message': f'Прием заказов {status_text}',
            'is_active': supplier.is_active
        })