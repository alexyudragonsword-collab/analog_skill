"""Fixtures shared across the suite."""

import pytest


@pytest.fixture
def isolated_settings(tmp_path):
    """QSettings writes to the real user store — point it somewhere
    disposable, and put the organisation back afterwards so nothing later in
    the session inherits the redirect."""
    from PySide6.QtCore import QCoreApplication, QSettings
    org, app_name = (QCoreApplication.organizationName(),
                     QCoreApplication.applicationName())
    fmt = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, str(tmp_path))
    QCoreApplication.setOrganizationName('AnalogStudioTest')
    QCoreApplication.setApplicationName('settings-isolation')
    yield
    QCoreApplication.setOrganizationName(org)
    QCoreApplication.setApplicationName(app_name)
    QSettings.setDefaultFormat(fmt)
