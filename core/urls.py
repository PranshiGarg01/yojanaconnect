from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.YojanaLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('', views.dashboard, name='dashboard'),

    path('schemes/', views.scheme_list, name='scheme_list'),
    path('schemes/<int:pk>/', views.scheme_detail, name='scheme_detail'),
    path('schemes/<int:pk>/apply/', views.apply_to_scheme, name='apply_to_scheme'),

    path('officer/schemes/', views.manage_schemes, name='manage_schemes'),
    path('officer/schemes/<int:scheme_id>/add-criteria/', views.add_criteria, name='add_criteria'),
    path('officer/applications/', views.application_list, name='application_list'),
    path('officer/applications/<int:pk>/review/', views.review_application, name='review_application'),
]