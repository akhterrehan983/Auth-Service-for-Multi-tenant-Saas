from django.contrib import admin

# Register your models here.

from .models import User, Organization, Role, Member

admin.site.register(User)
admin.site.register(Organization)
admin.site.register(Role)
admin.site.register(Member)
