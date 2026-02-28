from django.urls import path
from . import views

urlpatterns = [
    path('basket/', views.BasketView.as_view(), name='basket'),
    path('', views.OrderListView.as_view(), name='order-list'),
    path('<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('<int:pk>/confirm/', views.OrderConfirmView.as_view(), name='order-confirm'),
]