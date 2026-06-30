import os
import django
from django.contrib.auth import get_user_model

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hms_prj.settings')
django.setup()

User = get_user_model()
username = 'alliakinkunmi1'
email = 'alliakinkunmi1@gmail.com'
password = '12121212@1'

# We might also want to remove the old typo user if it exists
try:
    old_user = User.objects.get(username='alliaiakinkunmi1')
    old_user.delete()
except User.DoesNotExist:
    pass

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"Superuser '{username}' ({email}) created successfully.")
else:
    u = User.objects.get(username=username)
    u.email = email
    u.set_password(password)
    u.save()
    print(f"Superuser '{username}' password and email updated.")
