from django.conf import settings
from django.contrib.staticfiles.finders import AppDirectoriesFinder


class AppDirectoriesWithoutJazzminFinder(AppDirectoriesFinder):
    """Collect app static files while skipping Jazzmin's duplicate admin assets."""

    def __init__(self, app_names=None, *args, **kwargs):
        if app_names is None:
            app_names = [app for app in settings.INSTALLED_APPS if app != "jazzmin"]
        super().__init__(app_names=app_names, *args, **kwargs)
