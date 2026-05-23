from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('shop/', views.shop, name='shop'),
    
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('checkout/', views.checkout, name='checkout'),
    path('news/', views.news, name='news'),
    path('single-news/', views.single_news, name='single-news'),
    path('index-2/', views.index_2, name='index-2'),
    path('404/', views.error_404, name='404'),
    path('shop/single-product/', views.shop, name='shop-redirect'), # Fallback for no args
    path('shop/single-product/<int:pk>/', views.single_product, name='single-product'),
    
    # Cart URLs
    path('cart/', views.cart, name='cart'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/update/<int:item_id>/', views.update_cart, name='update_cart'),
    path('place-order/', views.place_order, name='place_order'),
    path('my-orders/', views.my_orders, name='my_orders'),
    
    # Auth URLs(autherization or authentication ky paths)
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.farmer_dashboard, name='farmer_dashboard'),
    path('dashboard/analyze-product/', views.analyze_product_listing, name='analyze_product_listing'),
    path('dashboard/delete/<int:pk>/', views.delete_product, name='delete_product'),
    path('dashboard/update/<int:pk>/', views.update_product, name='update_product'),
    path('dashboard/order/update/<int:order_id>/', views.seller_update_order_status, name='seller_update_order_status'),
]
