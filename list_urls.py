import inspect
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.viewsets import ViewSetMixin

def get_view_name(callback):
    try:
        if hasattr(callback, '__self__') and hasattr(callback.__self__, '__class__'):
            # Bound method: e.g., AdminSite.login
            cls_name = callback.__self__.__class__.__name__
            mod_name = callback.__self__.__class__.__module__
            func_name = callback.__name__
            return f"{mod_name}.{cls_name}.{func_name}"
        elif inspect.isfunction(callback) or inspect.ismethod(callback):
            return f"{callback.__module__}.{callback.__name__}"
        elif hasattr(callback, 'view_class'):
            return f"{callback.view_class.__module__}.{callback.view_class.__name__}"
        else:
            return str(callback)
    except Exception as e:
        return f"ERROR: {e}"

def get_http_methods(view):
    try:
        if hasattr(view, 'actions'):
            return [m.upper() for m in view.actions.keys()]
        elif hasattr(view, 'cls') and hasattr(view.cls, 'http_method_names'):
            return [m.upper() for m in view.cls.http_method_names]
        elif hasattr(view, 'http_method_names'):
            return [m.upper() for m in view.http_method_names]
    except:
        pass
    return ['GET']

def list_urls(urlpatterns, prefix=''):
    for pattern in urlpatterns:
        if isinstance(pattern, URLPattern):
            callback = pattern.callback
            method_list = get_http_methods(callback)
            view_name = get_view_name(callback)
            print(f"{prefix}{pattern.pattern}  [{', '.join(method_list)}] -> {view_name}")
        elif isinstance(pattern, URLResolver):
            list_urls(pattern.url_patterns, prefix + str(pattern.pattern))

# Entry point
list_urls(get_resolver().url_patterns)
