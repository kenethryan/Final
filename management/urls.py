from django.urls import path
from django.contrib.auth.decorators import login_required
from . import views

app_name = 'management'

urlpatterns = [
    # Unit URLs
    path('units/', login_required(views.unit_list), name='unit_list'),
    path('unit/add/', login_required(views.add_or_edit_unit), name='add_unit'),
    path('unit/<int:unit_id>/edit/', login_required(views.add_or_edit_unit), name='edit_unit'),
    path('unit/<int:unit_id>/delete/', login_required(views.unit_delete), name='unit_delete'),
    path('test-auth/', login_required(views.test_auth), name='test_auth'),
    path('tracking/', login_required(views.tracking), name='tracking'),
    
    # Driver URLs
    path('drivers/', login_required(views.driver_list), name='driver_list'),
    path('driver/<int:id>/delete/', login_required(views.driver_delete), name='driver_delete'),
    path('driver/<int:pk>/edit/', views.driver_edit, name='driver_edit'),
    
    # Extra Fund Management
    path('driver/<int:driver_id>/withdraw-savings/', login_required(views.withdraw_savings), name='withdraw_savings'),
    path('driver/<int:driver_id>/pay-debt/', login_required(views.pay_debt), name='pay_debt'),
    path('driver/<int:driver_id>/update-extra-fund/', login_required(views.update_extra_fund), name='update_extra_fund'),
    path('driver/<int:driver_id>/transactions/', login_required(views.driver_transactions), name='driver_transactions'),
    path('driver/<int:driver_id>/statement/', login_required(views.driver_statement), name='driver_statement'),
    path('driver/<int:driver_id>/statistics/', login_required(views.driver_statistics), name='driver_statistics'),

    # Maintenance URLs
    path('maintenance/', login_required(views.manage_damage_parts), name='manage_damage_parts'),
    path('maintenance/<int:damage_id>/mark-fixed/', login_required(views.mark_fixed), name='mark_fixed'),
    path('update-unit-status/', login_required(views.update_unit_status), name='update_unit_status'),

    path('unit/<int:unit_id>/info/', login_required(views.unit_info), name='unit_info'),
    path('unit/<int:unit_id>/statistics/', login_required(views.unit_statistics), name='unit_statistics'),
    path('unit/<int:unit_id>/position-history/', login_required(views.unit_position_history), name='unit_position_history'),
    path('unit/<int:unit_id>/import-position-history/', login_required(views.import_position_history), name='import_position_history'),
    path('unit/<int:unit_id>/live-position/', login_required(views.get_live_unit_position), name='get_live_unit_position'),
    path('unit-rental-history/<int:unit_id>/', login_required(views.unit_rental_history), name='unit_rental_history'),
    path('unit/<int:unit_id>/maintenance-history/', login_required(views.unit_maintenance_history), name='unit_maintenance_history'),
    path('confirm-remittance/<int:unit_id>/', login_required(views.confirm_remittance), name='confirm_remittance'),
    path('unit/assign-driver/', login_required(views.assign_driver), name='unit_assign_driver'),
    path('unit/assign-device/', login_required(views.assign_device), name='assign_device'),

    # Dashboard URL
    path('dashboard/', login_required(views.dashboard), name='dashboard'),

    # Admin URLs
    path('accounts/', login_required(views.accounts), name='accounts'),
    path('toggle-user-status/<int:user_id>/', login_required(views.toggle_user_status), name='toggle_user_status'),
    path('update-user-roles/<int:user_id>/', login_required(views.update_user_roles), name='update_user_roles'),
    path('activity-logs/', login_required(views.user_activity_logs), name='activity_logs'),
    path('activity-logs-pagination/', login_required(views.activity_logs_pagination), name='activity_logs_pagination'),
    path('admin/driver/toggle-status/<int:driver_id>/', login_required(views.toggle_driver_status), name='toggle_driver_status'),
    path('admin/remittance-amount/', login_required(views.update_remittance_amount), name='update_remittance_amount'),
    path('remittance-amount/', login_required(views.get_remittance_amount), name='get_remittance_amount'),
    
    # Unit & Driver overview pagination
    path('unit-overview-pagination/', login_required(views.unit_overview_pagination), name='unit_overview_pagination'),
    path('driver-overview-pagination/', login_required(views.driver_overview_pagination), name='driver_overview_pagination'),
    path("api/units/live/", login_required(views.live_unit_positions), name="live_unit_positions"),
    path("api/flespi/diagnostics/", login_required(views.flespi_api_diagnostics), name="flespi_api_diagnostics"),
    path("flespi/diagnostics/", login_required(views.flespi_diagnostics_page), name="flespi_diagnostics_page"),
]