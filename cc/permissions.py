from rest_framework import permissions

from cc.models import InstrumentUsage, InstrumentPermission, Instrument


class OwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            if hasattr(obj, 'user'):
                if obj.user == request.user:
                    return True
            if hasattr(obj, 'viewers'):
                print(obj.viewers.all())
                if request.user in obj.viewers.all():
                    return True
            if hasattr(obj, 'editors'):
                if request.user in obj.editors.all():
                    return True

            if hasattr(obj, 'enabled'):
                if obj.enabled:
                    return True
        if hasattr(obj, 'protocol'):
            if obj.protocol.user == request.user:
                return True
        if hasattr(obj, 'editors'):
            if request.user in obj.editors.all():
                return True
        if hasattr(obj, 'user'):
            if obj.user == request.user:
                return True

        return False


class InstrumentUsagePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_staff:
            return True
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method == 'POST':
            return True
        if request.method == 'DELETE':
            return True
        return False

    def has_object_permission(self, request, view, obj: InstrumentUsage):
        if request.user.is_staff:
            return True
        permission = InstrumentPermission.objects.filter(instrument=obj.instrument, user=request.user)
        if not permission.exists():
            permission = InstrumentPermission.objects.create(instrument=obj.instrument, user=request.user)
        else:
            permission = permission.first()
        if request.method in permissions.SAFE_METHODS and permission.can_view:
            return True
        if request.method == 'POST' and permission.can_book:
            return True
        if request.method == 'DELETE' and (obj.annotation.user == request.user or obj.user == request.user):
            return True
        if obj.annotation:
            if not obj.annotation.user == request.user:
                return False

        if not obj.user == request.user:
            return False
        if not permission.can_manage:
            return False



class InstrumentViewSetPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_staff:
            return True
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method == 'POST':
            return True
        return False

    def has_object_permission(self, request, view, obj: Instrument):
        if request.user.is_staff:
            return True

        permission = InstrumentPermission.objects.filter(instrument=obj, user=request.user)
        if not permission.exists():
            permission = InstrumentPermission.objects.create(instrument=obj, user=request.user)
        else:
            permission = permission.first()

        if request.method in permissions.SAFE_METHODS and permission.can_view:
            return True
        if not permission.can_manage:
            return False
        return False


