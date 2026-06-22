from django.urls import path, include
from .export_views import BulkExportViewSet
from .views import DataExportViewSet

# Direct mapping for Bulk Export
export_list = BulkExportViewSet.as_view({'get': 'list'})
export_detail = BulkExportViewSet.as_view({'get': 'retrieve'})

urlpatterns = [
    # Matches /api/export/
    path('', DataExportViewSet.as_view({'get': 'list', 'post': 'create'}), name='bulk-export-list'),
    
    # Matches /api/export/records/
    path('records/', DataExportViewSet.as_view({'get': 'list', 'post': 'create'}), name='data-export-records'),
    
    # Matches explicit download routes for record ids (integer pk)
    path('<int:pk>/download/', DataExportViewSet.as_view({'get': 'download'}), name='data-export-download'),
    path('<int:pk>/download', DataExportViewSet.as_view({'get': 'download'}), name='data-export-download-no-slash'),
    
    # Matches /api/export/units/ and /api/export/units
    path('<str:pk>/', export_detail, name='bulk-export-detail'),
    path('<str:pk>', export_detail, name='bulk-export-detail-no-slash'),
]
