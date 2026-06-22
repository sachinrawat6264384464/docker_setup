# support/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'ticket-categories', views.TicketCategoryViewSet, basename='ticket-category')
router.register(r'tickets', views.TicketViewSet, basename='ticket')
router.register(r'ticket-comments', views.TicketCommentViewSet, basename='ticket-comment')
router.register(r'faq-articles', views.FAQArticleViewSet, basename='faq-article')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', views.support_dashboard, name='support-dashboard'),
]
