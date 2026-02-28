import uuid
import logging
import secrets
import string
from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models, transaction
from django.utils import timezone
from django.core.validators import MaxValueValidator, RegexValidator, MinValueValidator
from django.contrib.auth.base_user import BaseUserManager
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Q, F, Avg
from django.core.exceptions import ValidationError

from jobs.models import TaskCategory, TaskSubjectArea

logger = logging.getLogger(__name__)

class GuestSession(models.Model):
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    
    shadow_client = models.OneToOneField(
        'User',
        on_delete=models.CASCADE,
        related_name='guest_session',
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Guest Session Link"
        verbose_name_plural = "Guest Session Links"

    def __str__(self):
        return f"Session: {self.session_key} -> User: {self.shadow_client_id}"


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    FREELANCER = "FREELANCER", "Freelancer"
    CLIENT = "CLIENT", "Client"

class RoleIDCounter(models.Model):
    role = models.CharField(max_length=10, choices=Role.choices, unique=True)
    next_id = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Role ID Counter"
        verbose_name_plural = "Role ID Counters"

    @classmethod
    def get_next_id(cls, role):
        with transaction.atomic():
            counter, created = cls.objects.select_for_update().get_or_create(
                role=role, defaults={"next_id": 1}
            )
            next_id = counter.next_id
            counter.next_id += 1
            counter.save(update_fields=['next_id'])
            return next_id

class UserManager(BaseUserManager):
    use_in_migrations = True

    def _generate_username_and_id(self, role):
        next_id_num = RoleIDCounter.get_next_id(role)
        if role == Role.CLIENT:
            username = f"Client{next_id_num:03d}"
        else:
            username = f"Remy{next_id_num:03d}"
        return username

    def _create_user(self, email, password, **extra_fields):
        if email:
            email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
            
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    @transaction.atomic
    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", Role.ADMIN)

        if not extra_fields.get("is_staff"):
            raise ValueError("Superuser must have is_staff=True.")
        if not extra_fields.get("is_superuser"):
            raise ValueError("Superuser must have is_superuser=True.")

        extra_fields["username"] = self._generate_username_and_id(Role.ADMIN)

        return self._create_user(email, password, **extra_fields)

    @transaction.atomic
    def create_user_by_role(self, role, email, password=None, phone=None, activate=False):
        if not email:
            raise ValueError("The Email must be set")
        email = self.normalize_email(email)

        existing = self.model.objects.filter(email=email).first()
        if existing:
            if existing.role == role:
                raise ValueError(f"A {role.lower()} with this email already exists.")
            else:
                raise ValueError(f"Email {email} is already registered as {existing.role.lower()}.")

        if not password:
            alphabet = string.ascii_letters + string.digits
            password = "".join(secrets.choice(alphabet) for _ in range(12))

        username = self._generate_username_and_id(role)

        user = self._create_user(
            email=email,
            password=password,
            username=username,
            phone=phone,
            role=role,
            is_active=activate,
        )

        logger.info(f"Created {role.lower()} {user.username} with email {email}")
        return user, password

    @transaction.atomic
    def create_shadow_client(self, session_key: str) -> "User":
        from chat.models import ChatThread

        guest_session = (
            GuestSession.objects
            .select_for_update()
            .select_related('shadow_client')
            .get_or_create(session_key=session_key)[0]
        )

        if guest_session.shadow_client:
            return guest_session.shadow_client

        existing_thread = ChatThread.objects.filter(
            guest_session_key=session_key,
            client__isnull=False,
            client__is_active=False,
            client__email__endswith='.shadow'
        ).select_related('client').first()

        if existing_thread and existing_thread.client:
            guest_session.shadow_client = existing_thread.client
            guest_session.save(update_fields=['shadow_client'])
            return existing_thread.client

        username = self._generate_username_and_id(Role.CLIENT)

        placeholder_email = (
            f"{username.lower()}."
            f"{secrets.token_hex(4)}."
            f"{session_key[:8]}.shadow"
        )

        alphabet = string.ascii_letters + string.digits
        temp_password = "".join(secrets.choice(alphabet) for _ in range(12))

        shadow_client = self.model(
            username=username,
            email=placeholder_email,
            role=Role.CLIENT,
            is_active=False,
        )
        shadow_client.set_password(temp_password)
        shadow_client.save(using=self._db)

        guest_session.shadow_client = shadow_client
        guest_session.save(update_fields=['shadow_client'])

        return shadow_client


    def create_client(self, email, phone=None, activate=False):
        return self.create_user_by_role(Role.CLIENT, email, None, phone, activate)

    def create_freelancer(self, email, password=None, phone=None, activate=False):
        return self.create_user_by_role(Role.FREELANCER, email, password, phone, activate)

class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=20, unique=True, blank=True, null=True)
    email = models.EmailField(unique=True, blank=False, null=False)
    phone_regex = RegexValidator(
        regex=r"^\+?1?\d{9,15}$",
        message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.",
    )
    phone = models.CharField(validators=[phone_regex], max_length=20, blank=True, null=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CLIENT)
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    warnings = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(3)])
    suspended_until = models.DateTimeField(null=True, blank=True)
    
    current_balance = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    pending_balance = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    total_earnings = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        indexes = [models.Index(fields=["email"]), models.Index(fields=["role"])]
        constraints = [
            models.CheckConstraint(check=models.Q(role__in=Role.values), name="valid_user_role")
        ]

    def __str__(self):
        return f"{self.username or self.email} ({self.role})"

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_suspended(self):
        return self.suspended_until and self.suspended_until > timezone.now()

    @property
    def average_rating(self):
        ratings = self.received_ratings.all()
        if ratings.exists():
            avg = self.received_ratings.aggregate(a=Avg('score'))['a']
        return round(avg, 1) if avg else None

    @property
    def is_freelancer(self):
        return self.role == Role.FREELANCER or self.role == Role.ADMIN

    @property
    def available_for_payout(self):
        return self.current_balance > Decimal('0.00')

    @property
    def total_payouts(self):
        from pay_freelancer.models import Payout, PayoutStatus
        return self.initiated_payouts.filter(status=PayoutStatus.SUCCESS).aggregate(
            total=models.Sum('payout_amount')
        )['total'] or Decimal('0.00')

    def add_to_balance(self, amount):
        User.objects.filter(pk=self.pk).update(
            current_balance=F('current_balance') + amount,
            total_earnings=F('total_earnings') + amount
        )

    def deduct_from_balance(self, amount):
        User.objects.filter(pk=self.pk).update(
            current_balance=F('current_balance') - amount
        )

    def release_pending_balance(self, amount):
        User.objects.filter(pk=self.pk).update(
            pending_balance=F('pending_balance') - amount,
            current_balance=F('current_balance') + amount
        )


class Admin(User):
    class Meta:
        proxy = True
        verbose_name = "Admin"
        verbose_name_plural = "Admins"

class FreelancerManager(models.Manager):
    def get_queryset(self):
        # return super().get_queryset().filter(Q(role=Role.FREELANCER) | Q(role=Role.ADMIN))
        return super().get_queryset().filter(Q(role=Role.FREELANCER))

class Freelancer(User):
    objects = FreelancerManager()

    class Meta:
        proxy = True
        verbose_name = "Freelancer"
        verbose_name_plural = "Freelancers"

class Client(User):
    class Meta:
        proxy = True
        verbose_name = "Client"
        verbose_name_plural = "Clients"

class FreelancerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name='freelancerprofile')
    categories = models.ManyToManyField(TaskCategory, related_name="freelancer_categories", blank=True)
    subjects = models.ManyToManyField(TaskSubjectArea, related_name="freelancer_profiles", blank=True)
    mpesa_number = models.CharField(max_length=20, blank=True, null=True)
    
    bio = models.TextField(blank=True, help_text="Brief introduction about yourself")
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    
    is_available = models.BooleanField(default=True, help_text="Currently available for new jobs")
    max_jobs_concurrent = models.PositiveIntegerField(default=3, help_text="Maximum jobs you can handle simultaneously")
    
    payout_preference = models.CharField(
        max_length=20,
        choices=[
            ('MPESA', 'M-Pesa'),
        ],
        default='MPESA'
    )   
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0)
    completed_jobs = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} Profile"

    def clean(self):
        from django.core.exceptions import ValidationError
        
        if self.payout_preference == 'MPESA' and not self.mpesa_number:
            raise ValidationError({
                'mpesa_number': 'M-Pesa number is required when M-Pesa is selected as payout method.'
            })

    @property
    def active_jobs_count(self):
        return self.user.jobs_as_freelancer.filter(status__in=['IN_PROGRESS', 'REVIEW']).count()

    @property
    def can_accept_new_jobs(self):
        return self.is_available and self.active_jobs_count < self.max_jobs_concurrent

    @property
    def has_payout_method(self):
        if self.payout_preference == 'MPESA':
            return bool(self.mpesa_number)
        return False

    @property
    def payout_method_details(self):
        if self.payout_preference == 'MPESA' and self.mpesa_number:
            return {
                'method': 'MPESA',
                'details': {
                    'phone_number': self.mpesa_number
                }
            }
        return None

    def update_payout_preference(self, preference, **kwargs):
        self.payout_preference = preference
        
        if preference == 'MPESA':
            self.mpesa_number = kwargs.get('mpesa_number', '')
        self.save()

    def update_rating(self, new_rating_score=None):
        ratings = self.user.received_ratings.all()
        if ratings.exists():
            self.rating = round(sum(r.score for r in ratings) / ratings.count(), 2)
            self.save(update_fields=['rating'])
            return self.rating
        return None

    def increment_completed_jobs(self):
        self.completed_jobs += 1
        self.save(update_fields=['completed_jobs'])

class Rating(models.Model):
    rater = models.ForeignKey(User, on_delete=models.CASCADE, related_name="given_ratings")
    rated_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_ratings")
    job = models.ForeignKey('orders.Job', on_delete=models.SET_NULL, null=True, blank=True, related_name='ratings')
    score = models.DecimalField(max_digits=2, decimal_places=1)
    review = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(score__gte=1) & Q(score__lte=5),
                name="valid_rating_score"
            ),
            models.UniqueConstraint(
                fields=['job', 'rater'],
                condition=Q(job__isnull=False),
                name='unique_job_rater_rating'
            ),
        ]

    def __str__(self):
        if self.job_id:
            return f"{self.rater.username} → {self.rated_user.username} ({self.job_id}): {self.score}"
        return f"{self.rater.username} → {self.rated_user.username}: {self.score}"

    def clean(self):
        if self.rater_id == self.rated_user_id:
            raise ValidationError("Users cannot rate themselves")

@receiver(post_save, sender=User)
def ensure_profiles_for_users(sender, instance: User, created, **kwargs):
    if created:
        try:
            UserProfile.objects.get_or_create(user=instance)
        except Exception:
            logger.exception("Failed to create UserProfile for user %s", instance.pk)

    if instance.role in (Role.FREELANCER, Role.ADMIN):
        try:
            instance.freelancerprofile
        except FreelancerProfile.DoesNotExist:
            try:
                FreelancerProfile.objects.create(user=instance)
            except Exception:
                logger.exception("Failed to create FreelancerProfile for user %s", instance.pk)

@receiver(post_save, sender=Rating)
def update_freelancer_rating(sender, instance, created, **kwargs):
    if instance.rated_user.is_freelancer:
        try:
            profile = instance.rated_user.freelancerprofile
            profile.update_rating()
        except FreelancerProfile.DoesNotExist:
            pass

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', primary_key=True)

    display_name = models.CharField(max_length=100, blank=True, help_text="Public display name")
    tagline = models.CharField(max_length=200, blank=True, help_text="Short tagline/headline")
    location = models.CharField(max_length=100, blank=True, help_text="City, Country")
    languages = models.JSONField(default=list, blank=True, help_text="List of languages spoken")

    about = models.TextField(blank=True, help_text="Rich text bio/about section")

    intro_video_url = models.URLField(blank=True, null=True, help_text="URL to intro video")

    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    cover_image = models.ImageField(upload_to='covers/', blank=True, null=True)

    is_public = models.BooleanField(default=True, help_text="Profile visible to public")
    account_status = models.CharField(
        max_length=20,
        choices=[
            ('ACTIVE', 'Active'),
            ('INACTIVE', 'Inactive'),
            ('SUSPENDED', 'Suspended'),
        ],
        default='ACTIVE'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

class FeaturedClient(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='featured_clients')
    client_name = models.CharField(max_length=100, help_text="Client/Brand name")
    client_logo = models.ImageField(upload_to='featured_clients/', blank=True, null=True)
    client_url = models.URLField(blank=True, null=True, help_text="Client website URL")
    description = models.TextField(blank=True, help_text="Brief description of work done")
    order = models.PositiveIntegerField(default=0, help_text="Display order (0-4 for max 5 clients)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Featured Client"
        verbose_name_plural = "Featured Clients"
        ordering = ['order', '-created_at']
        constraints = [
            models.CheckConstraint(
                check=Q(order__gte=0) & Q(order__lte=4),
                name='valid_featured_client_order'
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.client_name}"

class Portfolio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio_items')
    title = models.CharField(max_length=200, help_text="Project title")
    description = models.TextField(help_text="Project description")
    project_url = models.URLField(blank=True, null=True, help_text="Live project URL")
    image = models.ImageField(upload_to='portfolio/', blank=True, null=True)
    thumbnail = models.ImageField(upload_to='portfolio/thumbnails/', blank=True, null=True)

    client_name = models.CharField(max_length=100, blank=True, help_text="Client name")
    completion_date = models.DateField(blank=True, null=True)
    tags = models.JSONField(default=list, blank=True, help_text="Project tags/skills used")

    is_featured = models.BooleanField(default=False, help_text="Show on featured portfolio")
    order = models.PositiveIntegerField(default=0, help_text="Display order")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Portfolio Item"
        verbose_name_plural = "Portfolio Items"
        ordering = ['-is_featured', 'order', '-completion_date']

    def __str__(self):
        return f"{self.user.username} - {self.title}"

class WorkExperience(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='work_experience')
    job_title = models.CharField(max_length=200, help_text="Job title/position")
    company = models.CharField(max_length=200, help_text="Company name")
    location = models.CharField(max_length=100, blank=True, help_text="Job location")

    start_date = models.DateField(help_text="Start date")
    end_date = models.DateField(blank=True, null=True, help_text="End date (leave empty if current)")
    is_current = models.BooleanField(default=False, help_text="Currently working here")

    description = models.TextField(help_text="Job description and achievements")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Work Experience"
        verbose_name_plural = "Work Experience"
        ordering = ['-is_current', '-start_date']

    def __str__(self):
        return f"{self.user.username} - {self.job_title} at {self.company}"

class Education(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='education')
    institution = models.CharField(max_length=200, help_text="University/School name")
    degree = models.CharField(max_length=200, help_text="Degree/Qualification")
    field_of_study = models.CharField(max_length=200, blank=True, help_text="Major/Field of study")

    start_year = models.PositiveIntegerField(help_text="Start year")
    graduation_year = models.PositiveIntegerField(blank=True, null=True, help_text="Graduation year")
    is_current = models.BooleanField(default=False, help_text="Currently studying")

    grade = models.CharField(max_length=50, blank=True, help_text="GPA/Grade")
    description = models.TextField(blank=True, help_text="Additional details")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Education"
        verbose_name_plural = "Education"
        ordering = ['-is_current', '-graduation_year', '-start_year']

    def __str__(self):
        return f"{self.user.username} - {self.degree} at {self.institution}"

class Certification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='certifications')
    certification_name = models.CharField(max_length=200, help_text="Certification name")
    issuing_organization = models.CharField(max_length=200, help_text="Issuing organization")

    issue_year = models.PositiveIntegerField(help_text="Year obtained")
    expiry_year = models.PositiveIntegerField(blank=True, null=True, help_text="Expiry year (if applicable)")

    credential_id = models.CharField(max_length=100, blank=True, help_text="Credential ID")
    credential_url = models.URLField(blank=True, null=True, help_text="Verification URL")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Certification"
        verbose_name_plural = "Certifications"
        ordering = ['-issue_year']

    def __str__(self):
        return f"{self.user.username} - {self.certification_name}"

class Skill(models.Model):
    SKILL_LEVEL_CHOICES = [
        ('BEGINNER', 'Beginner'),
        ('INTERMEDIATE', 'Intermediate'),
        ('ADVANCED', 'Advanced'),
        ('EXPERT', 'Expert'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='skills')
    skill_name = models.CharField(max_length=100, help_text="Skill name")
    skill_level = models.CharField(
        max_length=20,
        choices=SKILL_LEVEL_CHOICES,
        default='INTERMEDIATE'
    )
    years_experience = models.PositiveIntegerField(default=0, help_text="Years of experience")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Skill"
        verbose_name_plural = "Skills"
        ordering = ['skill_name']
        unique_together = ['user', 'skill_name']

    def __str__(self):
        return f"{self.user.username} - {self.skill_name} ({self.skill_level})"
