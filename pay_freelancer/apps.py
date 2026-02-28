from django.apps import AppConfig

class PayFreelancerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pay_freelancer'
    
    def ready(self):
        import pay_freelancer.signals  