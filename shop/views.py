import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Sum, F
from django.urls import reverse
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme
from .models import Product, Category, Order, OrderItem, Review
from .forms import CustomUserCreationForm, ProductForm, CategoryForm, LoginForm, ReviewForm
from .ml.quality import assess_wheat_quality

def send_order_email_async(subject, message, email_from, recipient_list):
    """Helper function to send email in a separate thread."""
    try:
        send_mail(subject, message, email_from, recipient_list, fail_silently=False)
    except Exception as e:
        print(f"Async SMTP Error: {e}")

def home(request):
    products = Product.objects.select_related('farmer').all()[:8]
    return render(request, 'index.html', {'products': products})

def shop(request):
    products = Product.objects.select_related('farmer', 'category').all()
    categories_objs = Category.objects.all()
    categories = [(c.slug, c.name) for c in categories_objs]
    
    q = request.GET.get('q', '').strip()
    if q:
        q_lower = q.lower()
        # Quick navigation mapping
        quick_links = {'about': 'about', 'about us': 'about', 'contact': 'contact', 
                       'contact us': 'contact', 'news': 'news', 'home': 'home', 'cart': 'cart'}
        if q_lower in quick_links:
            return redirect(quick_links[q_lower])

        products = products.filter(Q(name__icontains=q) | Q(description__icontains=q))

    category = request.GET.get('category')
    if category:
        products = products.filter(category__slug=category)

    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)
    
    context = {
        'products': products,
        'q': q,
        'categories': categories,
        'selected_category': request.GET.get('category') 
    }
    return render(request, 'shop.html', context)

def about(request):
    return render(request, 'about.html')

def contact(request):
    return render(request, 'contact.html')

@login_required
def checkout(request):
    order = Order.objects.filter(customer=request.user, is_paid=False).first()
    context = {
        'order': order,
        'shipping_cost': settings.SHIPPING_COST,
    }
    return render(request, 'checkout.html', context)

def news(request):
    return render(request, 'news.html')

def single_news(request):
    return render(request, 'single-news.html')

def index_2(request):
    products = Product.objects.all()[:8]
    return render(request, 'index_2.html', {'products': products})

def error_404(request):
    return render(request, '404.html')

def single_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    reviews = product.reviews.all().order_by('-created_at')
    
    # Rating submit karne ka logic
    if request.method == 'POST' and request.user.is_authenticated:
        form = ReviewForm(request.POST)
        if form.is_valid():
            # Check if user already reviewed
            if Review.objects.filter(product=product, user=request.user).exists():
                messages.warning(request, "You have already reviewed this product.")
            else:
                review = form.save(commit=False)
                review.product = product
                review.user = request.user
                review.save()
                messages.success(request, "Thank you for your feedback!")
            return redirect('single-product', pk=pk)
    else:
        form = ReviewForm()

    products = Product.objects.exclude(pk=pk)[:4]
    context = {
        'product': product, 
        'products': products,
        'reviews': reviews,
        'form': form
    }
    return render(request, 'single-product.html', context)

class GuestOrderItem:
    def __init__(self, product, quantity):
        self.product = product
        self.quantity = quantity
        self.price = product.price
        self.id = product.id

    @property
    def get_total(self):
        return self.price * self.quantity

class GuestOrder:
    def __init__(self, items, total):
        self.items_list = items
        self.total = total

    @property
    def items(self):
        return self

    def all(self):
        return self.items_list

    @property
    def get_cart_total(self):
        return self.total

def cart(request):
    if request.user.is_authenticated:
        order = Order.objects.filter(customer=request.user, is_paid=False).first()
    else:
        cart_data = request.session.get('cart', {})
        items = []
        total = 0
        products = Product.objects.filter(id__in=cart_data.keys())
        for product in products:
            qty = cart_data.get(str(product.id))
            item = GuestOrderItem(product, qty)
            items.append(item)
            total += item.get_total
        order = GuestOrder(items, total)

    return render(request, 'cart.html', {'order': order})

def register(request):
    is_admin = request.user.is_authenticated and request.user.is_admin_user
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST, is_admin=is_admin)

        if form.is_valid():
            user = form.save(commit=False)
            if not is_admin:
                user.user_type = 'buyer' # Choices mein 'buyer' hai, 'customer' nahi
            user.save()
            
            login(request, user)
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('home')
    else:
        form = CustomUserCreationForm(is_admin=is_admin)

    next_param = request.GET.get('next') or request.POST.get('next')
    return render(request, 'register.html', {'form': form, 'next': next_param})

def login_view(request):
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # Merge Guest Cart to User Cart
            if 'cart' in request.session:
                session_cart = request.session['cart']
                if session_cart:
                    order, _ = Order.objects.get_or_create(customer=user, is_paid=False)
                    for p_id, qty in session_cart.items():
                        try:
                            product = Product.objects.get(id=p_id)
                            item, created = OrderItem.objects.get_or_create(order=order, product=product, defaults={'price': product.price, 'quantity': qty})
                            if not created:
                                item.quantity += qty
                                item.save()
                        except Product.DoesNotExist:
                            continue
                    del request.session['cart']

            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('home')
    else:
        form = LoginForm()
    next_param = request.GET.get('next') or request.POST.get('next')
    return render(request, 'login.html', {'form': form, 'next': next_param})

def logout_view(request):
    logout(request)
    return redirect('home')

def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    
    quantity = 1
    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity', 1))
        except ValueError:
            quantity = 1

    if quantity > product.stock:
        messages.warning(request, f'Only {product.stock} items are available for "{product.name}".')
        return redirect('single-product', pk=product.id)

    if request.user.is_authenticated:
        order, _ = Order.objects.get_or_create(customer=request.user, is_paid=False)
        
        order_item, created = OrderItem.objects.get_or_create(
            order=order, 
            product=product,
            defaults={'price': product.price, 'quantity': 0} 
        )

        if order_item.quantity + quantity <= product.stock:
            order_item.quantity += quantity
            order_item.save()
            if created:
                messages.success(request, f'"{product.name}" has been added to your cart.')
            else:
                messages.success(request, f'"{product.name}" quantity updated in your cart.')
        else:
            messages.warning(request, f'Cannot add more "{product.name}". Stock limit reached.')
    else:
        cart = request.session.get('cart', {})
        p_id = str(product_id)
        current_qty = cart.get(p_id, 0)
        
        if current_qty + quantity <= product.stock:
            cart[p_id] = current_qty + quantity
            request.session['cart'] = cart
            request.session.modified = True
            messages.success(request, f'"{product.name}" has been added to your cart.')
        else:
            messages.warning(request, f'Stock limit for "{product.name}" reached.')

    return redirect('cart')

@login_required
def update_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.user != product.farmer:
        raise PermissionDenied
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            updated_product = form.save(commit=False)
            updated_product.farmer = request.user
            try:
                updated_product.apply_market_price(strict=True)
            except ValidationError as exc:
                form.add_error(None, exc.messages[0])
            else:
                should_run_quality = (
                    updated_product.is_wheat_commodity and
                    updated_product.image and
                    (
                        'image' in form.changed_data or
                        'category' in form.changed_data or
                        not updated_product.quality_grade
                    )
                )
                if should_run_quality:
                    grade, confidence = assess_wheat_quality(updated_product.image)
                    updated_product.quality_grade = grade
                    updated_product.quality_confidence = confidence
                    messages.info(request, f'Wheat quality: Grade {grade} ({confidence}%).')
                elif not updated_product.is_wheat_commodity:
                    updated_product.quality_grade = None
                    updated_product.quality_confidence = None

                updated_product.save(allow_quality_override=should_run_quality)
                messages.success(request, f'Product "{updated_product.name}" updated with latest market price.')
                return redirect('farmer_dashboard')
    else:
        form = ProductForm(instance=product)
    
    return render(request, 'update_product.html', {'form': form, 'product': product})

def farmer_dashboard(request):
    if not request.user.is_seller:
        raise PermissionDenied # Unauthorized users ko error dikhayein
    
    products = Product.objects.filter(farmer=request.user)
    
    seller_orders = Order.objects.filter(
        items__product__farmer=request.user, 
        is_paid=True
    ).distinct().order_by('-updated_at')

    # Total Earnings calculate karein (Paid orders ka total)
    earnings = OrderItem.objects.filter(
        product__farmer=request.user,
        order__is_paid=True
    ).aggregate(
        total=Sum(F('quantity') * F('price'))
    )['total'] or 0

    product_form = ProductForm()
    category_form = CategoryForm()

    if request.method == 'POST':
        if 'create_category' in request.POST:
            category_form = CategoryForm(request.POST)
            if category_form.is_valid():
                category_form.save()
                return redirect('farmer_dashboard')
        else:
            product_form = ProductForm(request.POST, request.FILES)
            if product_form.is_valid():
                product = product_form.save(commit=False)
                product.farmer = request.user
                try:
                    product.apply_market_price(strict=True)
                except ValidationError as exc:
                    product_form.add_error(None, exc.messages[0])
                else:
                    if product.is_wheat_commodity and product.image:
                        grade, confidence = assess_wheat_quality(product.image)
                        product.quality_grade = grade
                        product.quality_confidence = confidence
                        messages.info(request, f'Wheat quality: Grade {grade} ({confidence}%).')
                    else:
                        product.quality_grade = None
                        product.quality_confidence = None

                    product.save()
                    messages.success(request, f'Product "{product.name}" published with market-linked pricing.')
                    return redirect('farmer_dashboard')
        
    context = {
        'products': products, 
        'earnings': earnings,
        'form': product_form, 
        'category_form': category_form,
        'seller_orders': seller_orders,
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'farmer_dashboard.html', context)

@login_required
def delete_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.user == product.farmer:
        product.delete()
    return redirect('farmer_dashboard')

def update_cart(request, item_id):
    if request.user.is_authenticated:
        try:
            order_item = OrderItem.objects.get(id=item_id, order__customer=request.user, order__is_paid=False)
        except OrderItem.DoesNotExist:
            messages.error(request, "This item was not found in your cart.")
            return redirect('cart')

        if request.method == 'POST':
            try:
                quantity = int(request.POST.get('quantity'))
                if quantity > 0:
                    if quantity <= order_item.product.stock:
                        order_item.quantity = quantity
                        order_item.save()
                        messages.success(request, f'Quantity for "{order_item.product.name}" has been updated.')
                    else:
                        messages.warning(request, f'Only {order_item.product.stock} items are available for "{order_item.product.name}".')
                else:
                    product_name = order_item.product.name
                    order_item.delete()
                    messages.success(request, f'"{product_name}" has been removed from your cart.')
            except (ValueError, TypeError):
                messages.error(request, "Invalid quantity provided.")
    else:
        cart = request.session.get('cart', {})
        p_id = str(item_id)
        if request.method == 'POST':
            try:
                quantity = int(request.POST.get('quantity'))
                product = get_object_or_404(Product, id=item_id)
                if quantity > 0:
                    if quantity <= product.stock:
                        cart[p_id] = quantity
                        request.session['cart'] = cart
                        messages.success(request, f'Quantity for "{product.name}" has been updated.')
                    else:
                        messages.warning(request, f'Only {product.stock} items are available for "{product.name}".')
                else:
                    if p_id in cart:
                        del cart[p_id]
                        request.session['cart'] = cart
                        messages.success(request, f'"{product.name}" has been removed from your cart.')
            except (ValueError, TypeError):
                messages.error(request, "Invalid quantity provided.")

    return redirect('cart')

def remove_from_cart(request, item_id):
    if request.user.is_authenticated:
        try:
            order_item = OrderItem.objects.get(id=item_id, order__customer=request.user, order__is_paid=False)
            order_item.delete()
            messages.success(request, "Item has been removed from your cart.")
        except OrderItem.DoesNotExist:
            messages.error(request, "This item was not found in your cart.")
    else:
        cart = request.session.get('cart', {})
        p_id = str(item_id)
        if p_id in cart:
            del cart[p_id]
            request.session['cart'] = cart
            messages.success(request, "Item has been removed from your cart.")
        else:
            messages.error(request, "This item was not found in your cart.")
            
    return redirect('cart')

@login_required
def place_order(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        address = request.POST.get('address')
        phone = request.POST.get('phone')

        order = Order.objects.filter(customer=request.user, is_paid=False).first()
        if order:
            order.is_paid = True
            
            order.shipping_address = address
            order.phone = phone
            order.full_name = name
            # Settings se shipping cost use kar rahe hain
            order.total_price = order.get_cart_total + settings.SHIPPING_COST
            
            order.save()

            # Inventory update
            for item in order.items.all():
                product = item.product
                product.stock -= item.quantity
                product.save()

            # Email content taiyar karein
            subject = f"Order Received - Order #{order.id}"
            message = f"Hi {name},\n\nYour order has been placed and is pending confirmation.\n\n"
            message += f"Order ID: {order.id}\n"
            message += f"Date: {order.updated_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            
            message += "Items:\n"
            for item in order.items.all():
                message += f"- {item.product.name}: {item.quantity} x ${item.price} = ${item.get_total}\n"
            
            message += f"\nTotal Price (including ${settings.SHIPPING_COST} shipping): ${order.total_price}\n\n"
            message += f"Shipping Address:\n{address}\nPhone: {phone}\n\n"
            message += "Thank you for shopping with us!"
            
            email_from = settings.EMAIL_HOST_USER
            recipient_list = [email, ]

            # Thread start karein taake view block na ho
            email_thread = threading.Thread(
                target=send_order_email_async, 
                args=(subject, message, email_from, recipient_list)
            )
            email_thread.start()

            messages.success(request, "Your order has been placed successfully!")
            return redirect('my_orders')
        else:
            messages.error(request, "No active order found in your cart.")
    return redirect('checkout')

@login_required
def my_orders(request):
    orders = Order.objects.filter(customer=request.user, is_paid=True).order_by('-updated_at')
    return render(request, 'my_orders.html', {'orders': orders})

@login_required
def seller_update_order_status(request, order_id):
    if request.user.user_type != 'seller':
        raise PermissionDenied

    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        if order.items.filter(product__farmer=request.user).exists():
            new_status = request.POST.get('status')
            if new_status in [choice[0] for choice in Order.STATUS_CHOICES]:
                order.status = new_status
                order.save()
                messages.success(request, f"Order #{order.id} status updated to {new_status}.")
            else:
                messages.error(request, f"Invalid status: {new_status}")
    return redirect('farmer_dashboard')