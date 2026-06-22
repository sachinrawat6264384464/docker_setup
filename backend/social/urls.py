# social/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PostViewSet, PostCommentViewSet

router = DefaultRouter()
router.register(r'posts', PostViewSet)
router.register(r'comments', PostCommentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
