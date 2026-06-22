from django.urls import path
from .views import (
    PublicPostListView, PublicPostDetailView, PublicCategoryListView,
    PostCommentListView, PostLikeToggleView,
    AdminPostListView, AdminPostDetailView,
    AdminCategoryView, AdminCategoryDetailView,
    AdminTagView, AdminCommentView,
    AdminImageUploadView,
)

urlpatterns = [
    # Public
    path('posts/',                          PublicPostListView.as_view(),     name='blog-posts'),
    path('posts/<slug:slug>/',              PublicPostDetailView.as_view(),   name='blog-post-detail'),
    path('posts/<slug:slug>/comments/',     PostCommentListView.as_view(),    name='blog-comments'),
    path('posts/<slug:slug>/like/',         PostLikeToggleView.as_view(),     name='blog-post-like'),
    path('categories/',                     PublicCategoryListView.as_view(), name='blog-categories'),

    # Admin
    path('admin/posts/',                    AdminPostListView.as_view(),       name='admin-blog-posts'),
    path('admin/posts/<slug:slug>/',        AdminPostDetailView.as_view(),     name='admin-blog-post'),
    path('admin/categories/',              AdminCategoryView.as_view(),       name='admin-blog-categories'),
    path('admin/categories/<int:pk>/',     AdminCategoryDetailView.as_view(), name='admin-blog-category-detail'),
    path('admin/tags/',                     AdminTagView.as_view(),            name='admin-blog-tags'),
    path('admin/comments/',                AdminCommentView.as_view(),        name='admin-blog-comments'),
    path('admin/comments/<uuid:pk>/',      AdminCommentView.as_view(),        name='admin-blog-comment'),
    path('admin/upload-image/',            AdminImageUploadView.as_view(),    name='admin-blog-upload-image'),
]
