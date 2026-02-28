from django.urls import path
from . import views

urlpatterns = [
    path('profile/', views.SupplierProfileView.as_view(), name='supplier-profile'),
    path('products/', views.SupplierProductListView.as_view(), name='supplier-products'),
    path('products/<int:pk>/', views.SupplierProductDetailView.as_view(), name='supplier-product-detail'),
    path('orders/', views.SupplierOrderListView.as_view(), name='supplier-orders'),
    path('orders/<int:pk>/', views.SupplierOrderDetailView.as_view(), name='supplier-order-detail'),
    path('toggle-receiving/', views.ToggleOrderReceivingView.as_view(), name='toggle-receiving'),
]