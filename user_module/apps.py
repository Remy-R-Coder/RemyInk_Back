from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class UserModuleConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'user_module'

    verbose_name = _('User Module')
    def ready(self):
        try:
            import user_module.signals  # noqa F401
        except ImportError:
            pass
