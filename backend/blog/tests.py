from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from blog.models import Post, Category, PostLike

User = get_user_model()


class PostModelTest(TestCase):
    def setUp(self):
        self.post = Post.objects.create(
            title='Test Post',
            content='Hello world ' * 200,
            status='published',
        )

    def test_post_has_like_count_default_zero(self):
        self.assertEqual(self.post.like_count, 0)

    def test_post_has_featured_image_field(self):
        self.assertEqual(self.post.featured_image, '')

    def test_post_has_canonical_url_field(self):
        self.assertEqual(self.post.canonical_url, '')


class PostLikeModelTest(TestCase):
    def setUp(self):
        self.post = Post.objects.create(title='Post', content='x', status='published')

    def test_create_like(self):
        like = PostLike.objects.create(post=self.post, ip_address='1.2.3.4')
        self.assertEqual(like.post, self.post)
        self.assertEqual(like.ip_address, '1.2.3.4')

    def test_unique_ip_per_post(self):
        PostLike.objects.create(post=self.post, ip_address='1.2.3.4')
        with self.assertRaises(IntegrityError):
            PostLike.objects.create(post=self.post, ip_address='1.2.3.4')


import json
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from blog.models import PostLike  # Post, Category, User already imported in Task 1


class PostLikeToggleTest(APITestCase):
    def setUp(self):
        self.post = Post.objects.create(title='P', content='x', status='published')
        self.url = f'/api/blog/posts/{self.post.slug}/like/'

    def test_like_increments_count(self):
        resp = self.client.post(self.url, REMOTE_ADDR='10.0.0.1')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['liked'])
        self.assertEqual(data['count'], 1)

    def test_unlike_decrements_count(self):
        self.client.post(self.url, REMOTE_ADDR='10.0.0.1')
        resp = self.client.post(self.url, REMOTE_ADDR='10.0.0.1')
        data = resp.json()
        self.assertFalse(data['liked'])
        self.assertEqual(data['count'], 0)

    def test_different_ip_can_like(self):
        self.client.post(self.url, REMOTE_ADDR='10.0.0.1')
        resp = self.client.post(self.url, REMOTE_ADDR='10.0.0.2')
        self.post.refresh_from_db()
        self.assertEqual(self.post.like_count, 2)


class AdminCategoryDeleteTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('su', 'su@t.com', 'pass')
        self.client.force_authenticate(user=self.user)
        self.cat = Category.objects.create(name='DeleteMe')

    def test_delete_empty_category(self):
        url = f'/api/blog/admin/categories/{self.cat.id}/'
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)

    def test_delete_category_with_posts_returns_400(self):
        Post.objects.create(title='P', content='x', category=self.cat, status='published')
        url = f'/api/blog/admin/categories/{self.cat.id}/'
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 400)
