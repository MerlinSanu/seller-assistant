from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/transactions/", views.transactions_api, name="transactions_api"),
    path("api/summary/", views.summary_api, name="summary_api"),
    path("api/chat/", views.chat_api, name="chat_api"),
]