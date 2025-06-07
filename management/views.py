from django.db import transaction, IntegrityError
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Unit, Driver, DamagePart, Remittance, DamageReport, RemittanceAmount, DevicePosition
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models import Sum, Q, Count, Avg, F
from decimal import Decimal, InvalidOperation
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.serializers import serialize
from django.http import Http404, JsonResponse, HttpResponse, HttpResponseRedirect
from .utils import generate_remittance_pdf
import logging
import json
from django.db.models import Exists, OuterRef
from django.views.decorators.csrf import csrf_exempt
from account.models import UserProfile, UserActivityLog
import requests
from django.conf import settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.cache import cache
import time
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from django.template.loader import render_to_string
from .flespi import FlespiAPI


logger = logging.getLogger(__name__)

def is_management_staff(user):
    """Check if a user has management permissions."""
    logger.info(f"Checking management staff for user: {user}, authenticated: {user.is_authenticated}")
    # Allow all authenticated users to manage units for now
    return user.is_authenticated

def is_admin(user):
    return user.is_superuser

@login_required
def dashboard(request):
    # Date filtering parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # Base queryset for remittances
    remittances = Remittance.objects.all().order_by('-date')

    # Apply date filters if they exist
    if start_date:
        start_date = timezone.datetime.strptime(start_date, "%Y-%m-%d").date()
        remittances = remittances.filter(date__gte=start_date)
    if end_date:
        end_date = timezone.datetime.strptime(end_date, "%Y-%m-%d").date()
        remittances = remittances.filter(date__lte=end_date)

    # Show all remittances for the filtered range, or last 5 if no filter
    if start_date or end_date:
        recent_remittances = remittances
    else:
        recent_remittances = remittances[:5]

    # Handle PDF export
    if 'export' in request.GET and request.GET['export'] == 'pdf':
        buffer = generate_remittance_pdf(
            remittances,
            start_date=start_date,
            end_date=end_date
        )
        filename = f"remittances_{timezone.now().strftime('%Y%m%d%H%M%S')}.pdf"
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Content-Type'] = 'application/pdf'
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    # Get the required remittance amount for payment comparison
    remittance_amount = RemittanceAmount.objects.first()
    if not remittance_amount:
        remittance_amount = RemittanceAmount.objects.create(amount=200.00)
    required_amount = remittance_amount.amount

    # Unit statistics
    units = Unit.objects.all()
    total_units = units.count()
    unit_status_counts = {
        'stand_by': units.filter(status='stand_by').count(),
        'in_use': units.filter(status='in_use').count(),
        'under_maintenance': units.filter(status='under_maintenance').count(),
        'out_of_service': units.filter(status='out_of_service').count(),
    }

    # Check for units with high maintenance reports in the last month
    one_month_ago = timezone.now() - timedelta(days=30)
    
    # Count units with 10+ maintenance reports in the last month
    high_maintenance_units = 0
    critical_maintenance_units = 0
    
    for unit in units:
        monthly_reports_count = DamageReport.objects.filter(
            unit=unit, reported_date__gte=one_month_ago
        ).count()
        
        if monthly_reports_count >= 20:
            critical_maintenance_units += 1
        elif monthly_reports_count >= 10:
            high_maintenance_units += 1
    
    # Driver statistics
    total_drivers = Driver.objects.filter(status='active').count()
    active_drivers = Driver.objects.filter(status='active').count()

    # Weekly income data
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    weekly_income = [0] * 7
    for i in range(7):
        day = week_start + timedelta(days=i)
        day_income = remittances.filter(
            date=day
        ).aggregate(
            total=Sum('remit_amount')
        )['total'] or 0
        weekly_income[i] = float(day_income)

    # Monthly income data
    monthly_income = [0] * 12
    current_year = timezone.now().year
    for month in range(1, 13):
        month_income = remittances.filter(
            date__year=current_year,
            date__month=month
        ).aggregate(
            total=Sum('remit_amount')
        )['total'] or 0
        monthly_income[month-1] = float(month_income)

    context = {
        'unit_status_counts': unit_status_counts,
        'active_drivers': active_drivers,
        'total_drivers': total_drivers,
        'total_units': total_units,
        'recent_remittances': recent_remittances,
        'start_date': start_date,
        'end_date': end_date,
        'weekly_income': weekly_income,
        'monthly_income': monthly_income,
        'high_maintenance_units': high_maintenance_units,
        'critical_maintenance_units': critical_maintenance_units,
        'required_amount': required_amount,  # Add the required amount to the context
    }

    return render(request, 'dashboard.html', context)

@login_required
def unit_list(request):
    """View for listing all units with their current status and driver assignments."""
    # Get all units with their current driver assignments
    units = Unit.objects.all().select_related('driver')
    
    # Separate units into active and out of service
    active_units = []
    out_of_service_units = []
    
    for unit in units:
        if unit.status == 'out_of_service':
            out_of_service_units.append(unit)
        else:
            active_units.append(unit)
    
    # Sort active units by PO
    active_units.sort(key=lambda x: x.unit_PO)
    
    # Combine lists with out of service units at the end
    units = active_units + out_of_service_units
    
    # Get all drivers for the dropdown
    drivers = Driver.objects.filter(status='active')
    
    # Get list of assigned driver IDs
    assigned_drivers = [unit.driver.id for unit in units if unit.driver]

    # Implement pagination
    paginator = Paginator(units, 10)  # Show 10 units per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'drivers': drivers,
        'assigned_drivers': assigned_drivers,
    }
    return render(request, 'unit_list.html', context)

@require_POST
def update_unit_status(request):
    """Update unit status and log the change."""
    try:
        unit_id = request.POST.get('unit_id')
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '')

        unit = get_object_or_404(Unit, id=unit_id)
        
        # If unit is already out of service, prevent any changes
        if unit.status == 'out_of_service':
            return JsonResponse({
                'success': False,
                'error': 'This unit is out of service and cannot be modified.'
            })
        
        # If changing to out of service, remove driver and device
        if new_status == 'out_of_service':
            if unit.driver:
                unit.driver = None
            if unit.flespi_device_id:
                unit.flespi_device_id = None
        
        unit.status = new_status
        unit.updated_at = timezone.now()  # Explicitly update the updated_at field
        unit.save()

        # Log the status change
        UserActivityLog.objects.create(
            user=request.user,
            action='status_change',
            details=f"Changed status of unit {unit.unit_PO} to {new_status}"
        )

        return JsonResponse({
            'success': True,
            'unit': {
                'id': unit.id,
                'po': unit.unit_PO,
                'status': unit.status,
                'driver': unit.driver.driver_name if unit.driver else None,
                'device_id': unit.flespi_device_id
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def unit_info(request, unit_id):
    unit = get_object_or_404(Unit, id=unit_id)
    data = {
        'unit_PO': unit.unit_PO,
        'unit_made': unit.unit_made.strftime("%Y-%m-%d"),
        'status': unit.get_status_display(),
        'driver': unit.driver.driver_name if unit.driver else None,
        'driver_savings': str(unit.driver.savings) if unit.driver else '0.00',
        'driver_debt': str(unit.driver.debt) if unit.driver else '0.00',
        'device_imei': unit.device_imei if unit.device_imei else None,
        'flespi_device_id': unit.flespi_device_id if unit.flespi_device_id else None,
        'updated_at': unit.updated_at.strftime("%Y-%m-%d %H:%M:%S") if unit.updated_at else None,
    }
    return JsonResponse(data)

@login_required
def unit_rental_history(request, unit_id):
    unit = get_object_or_404(Unit, id=unit_id)
    rentals = Remittance.objects.filter(unit=unit).order_by('-date')

    data = [{
        'driver': rental.driver.driver_name if rental.driver else 'N/A',
        'start_date': rental.date.isoformat() if rental.date else '',
        'returned_at': rental.released_at.isoformat() if rental.released_at else '',
        'remit_amount': str(rental.remit_amount),
        'savings_amount': str(rental.savings_amount),
        'payment_method': get_payment_method_display(rental.remit_amount, rental.savings_amount)
    } for rental in rentals]

    return JsonResponse({'rentals': data})

def get_payment_method_display(remit_amount, savings_amount):
    remit_amount = remit_amount or 0
    savings_amount = savings_amount or 0
    if remit_amount > 0 and savings_amount > 0:
        return "Both (Cash + Extra Fund)"
    elif remit_amount > 0:
        return "Cash"
    elif savings_amount > 0:
        return "Extra Fund"
    elif remit_amount == 0 and savings_amount == 0:
        return "Rental Balance"
    return "N/A"

@login_required
def add_or_edit_unit(request, unit_id=None):
    if request.method == 'POST':
        unit_PO = request.POST.get('unit_PO')
        unit_made = request.POST.get('unit_made')
        status = request.POST.get('status', 'stand_by')
        driver_id = request.POST.get('driver_id')

        if Unit.objects.filter(unit_PO=unit_PO).exclude(id=unit_id).exists():
            messages.error(request, 'Unit PO already exists.')
            return redirect('management:unit_list')

        try:
            if unit_id:
                unit = get_object_or_404(Unit, id=unit_id)
                unit.unit_PO = unit_PO
                unit.unit_made = unit_made
                unit.status = status
                unit.driver = get_object_or_404(Driver, id=driver_id) if driver_id else None
                unit.save()
                # Log unit update
                UserActivityLog.objects.create(
                    user=request.user,
                    action='edit_unit',
                    details=f"Edited unit {unit.unit_PO} (ID: {unit.id})"
                )
                messages.success(request, 'Unit updated successfully.')
            else:
                unit = Unit.objects.create(
                    unit_PO=unit_PO,
                    unit_made=unit_made,
                    status=status,
                    driver_id=driver_id if driver_id else None
                )
                # Log unit creation
                UserActivityLog.objects.create(
                    user=request.user,
                    action='add_unit',
                    details=f"Added unit {unit.unit_PO} (ID: {unit.id})"
                )
                messages.success(request, 'Unit added successfully.')
        except IntegrityError:
            messages.error(request, 'Duplicate unit PO. Ensure uniqueness.')

        return redirect('management:unit_list')

    unit = get_object_or_404(Unit, id=unit_id) if unit_id else None
    drivers = Driver.objects.all()
    return render(request, 'unit_form_modal.html', {
        'unit': unit,
        'drivers': drivers,
        'status_choices': Unit.STATUS_CHOICES,
    })

@login_required
def unit_maintenance_history(request, unit_id):
    """Get maintenance history for a unit."""
    unit = get_object_or_404(Unit, id=unit_id)
    damage_reports = DamageReport.objects.filter(unit=unit).order_by('-reported_date')
    
    history = [{
        'description': report.description,
        'reported_date': report.reported_date,
        'is_fixed': report.is_fixed,
        'fixed_date': report.fixed_date if hasattr(report, 'fixed_date') else None
    } for report in damage_reports]
    
    return JsonResponse(history, safe=False)

@login_required
def test_auth(request):
    """This is a test view to check if authentication is maintained"""
    logger.info(f"Test auth view accessed by {request.user}")
    messages.success(request, 'Authentication test successful')
    return redirect('management:unit_list')

#@user_passes_test(is_management_staff)  # Comment out this decorator for now to isolate the issue
@login_required
def unit_delete(request, unit_id):
    # Log everything to debug the issue
    logger.info(f"unit_delete called with unit_id={unit_id}, user={request.user}, authenticated={request.user.is_authenticated}")
    
    if not is_management_staff(request.user):
        logger.warning(f"User {request.user} attempted to delete unit {unit_id} but lacks management permissions")
        messages.error(request, "You don't have permission to delete units")
        return redirect('/management/units/')
        
    try:
        unit = get_object_or_404(Unit, id=unit_id)
        if request.method == 'POST':
            try:
                unit_po = unit.unit_PO  # Save unit PO for message before deletion
                unit.delete()
                logger.warning(f"{request.user} deleted unit {unit_id} ({unit_po})")
                # Log unit deletion
                UserActivityLog.objects.create(
                    user=request.user,
                    action='delete_unit',
                    details=f"Deleted unit {unit_po} (ID: {unit_id})"
                )
                messages.success(request, f'Unit {unit_po} deleted successfully.')
                logger.info(f"Successfully deleted unit {unit_id}, redirecting to unit_list")
                response = redirect('/management/units/')
                return response
            except Exception as e:
                logger.error(f"Error deleting unit {unit_id}: {str(e)}", exc_info=True)
                messages.error(request, f'Error deleting unit: {str(e)}')
                response = redirect('/management/units/')
                return response
        # GET request, redirect to unit list
        logger.info(f"GET request to unit_delete, redirecting to unit_list")
        response = redirect('/management/units/')
        return response
    except Exception as e:
        logger.error(f"Unexpected error in unit_delete view: {str(e)}", exc_info=True)
        messages.error(request, f'An unexpected error occurred: {str(e)}')
        response = redirect('/management/units/')
        return response


@login_required
def driver_list(request):
    # Get search query
    search_query = request.GET.get('q', '')
    
    # Base queryset: Exclude fired drivers
    drivers = Driver.objects.exclude(status='fired')
    
    # Apply search filter if query exists
    if search_query:
        drivers = drivers.filter(
            Q(driver_PD__icontains=search_query) |
            Q(driver_name__icontains=search_query) |
            Q(contact_number__icontains=search_query)
        )
    
    # Order by driver PD
    drivers = drivers.order_by('driver_name')

    # --- Delinquent driver logic ---
    from .models import RemittanceAmount, Remittance
    delinquent_drivers = []
    delinquent_driver_ids = set()
    remittance_amount_obj = RemittanceAmount.objects.first()
    required_amount = float(remittance_amount_obj.amount) if remittance_amount_obj else 200.0
    for driver in drivers:
        debt = float(driver.debt or 0)
        remittances = Remittance.objects.filter(driver=driver)
        total_remit = sum(float(r.remit_amount or 0) for r in remittances)
        count_remit = remittances.count()
        avg_remit = (total_remit / count_remit) if count_remit > 0 else 0
        if debt > 1000 or (required_amount > 0 and avg_remit < 0.5 * required_amount):
            delinquent_drivers.append(driver)
            delinquent_driver_ids.add(driver.id)
    # --- End delinquent logic ---

    if request.method == 'POST':
        driver_PD = request.POST.get('driver_PD')
        contact_number = request.POST.get('contact_number')
        driver_name = request.POST.get('driver_name')
        status = request.POST.get('status', 'active')
        driver_id = request.POST.get('driver_id')
        profile_picture = request.FILES.get('profile_picture')

        try:
            if driver_id:
                driver = get_object_or_404(Driver, id=driver_id)
                driver.driver_PD = driver_PD
                driver.contact_number = contact_number
                driver.driver_name = driver_name
                driver.status = status

                # Update profile picture if new one was uploaded
                if profile_picture:
                    driver.profile_picture = profile_picture

                driver.save()
                messages.success(request, 'Driver updated successfully.')
            else:
                if Driver.objects.filter(driver_PD=driver_PD).exists():
                    messages.error(request, 'Driver PD already exists.')
                else:
                    Driver.objects.create(
                        driver_PD=driver_PD,
                        contact_number=contact_number,
                        driver_name=driver_name,
                        status=status,
                        profile_picture=profile_picture  # Add profile picture
                    )
                    messages.success(request, 'Driver added successfully.')
        except IntegrityError:
            messages.error(request, 'Duplicate driver PD. Ensure uniqueness.')

        return redirect('management:driver_list')
    
    # Pagination
    paginator = Paginator(drivers, 10)  # Show 10 drivers per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get list of assigned drivers
    assigned_drivers = Unit.objects.exclude(driver=None).values_list('driver_id', flat=True)
    
    return render(request, 'management/driver_list.html', {
        'page_obj': page_obj,
        'drivers': drivers,
        'search_query': search_query,
        'assigned_drivers': list(assigned_drivers),
        'delinquent_drivers': delinquent_drivers,
        'delinquent_driver_ids': list(delinquent_driver_ids),
    })
def driver_edit(request, pk):
    driver = get_object_or_404(Driver, pk=pk)

    if request.method == 'POST':
        # Update basic fields
        driver.driver_PD = request.POST.get('driver_PD')
        driver.driver_name = request.POST.get('driver_name')
        driver.contact_number = request.POST.get('contact_number')
        driver.status = request.POST.get('status')

        # Handle profile picture upload
        if 'profile_picture' in request.FILES:
            driver.profile_picture = request.FILES['profile_picture']

        try:
            driver.save()
            # Log driver edit
            UserActivityLog.objects.create(
                user=request.user,
                action='edit_driver',
                details=f"Edited driver {driver.driver_name} (ID: {driver.id})"
            )
            messages.success(request, 'Driver information updated successfully!')
            return redirect('management:driver_list')
        except Exception as e:
            messages.error(request, f'Error updating driver: {str(e)}')
            return redirect('management:driver_list')

    # If GET request, show edit form (handled by the frontend JavaScript)
    return redirect('management:driver_list')

@login_required
def driver_delete(request, id):
    driver = get_object_or_404(Driver, id=id)
    if request.method == 'POST':
        # Instead of deleting, mark as inactive
        driver.status = 'inactive'
        driver.save()
        logger.warning(f"{request.user} marked driver {id} as inactive")
        # Log driver deletion (inactive)
        UserActivityLog.objects.create(
            user=request.user,
            action='delete_driver',
            details=f"Marked driver {driver.driver_name} (ID: {driver.id}) as inactive"
        )
        messages.success(request, 'Driver removed from list successfully.')
    return redirect('management:driver_list')

@transaction.atomic
@login_required
def withdraw_savings(request, driver_id):
    driver = get_object_or_404(Driver, id=driver_id)

    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount'))
            if amount <= 0:
                messages.error(request, 'Amount must be positive.')
            elif amount > driver.savings:
                messages.error(request, 'Withdrawal amount exceeds available Extra Fund.')
            else:
                driver.savings -= amount
                driver.save()
                # Log withdrawal
                UserActivityLog.objects.create(
                    user=request.user,
                    action='withdraw_savings',
                    details=f"Withdrew ₱{amount:,.2f} from Extra Fund for driver {driver.driver_name} (ID: {driver.id})"
                )
                messages.success(request, f'Successfully withdrew ₱{amount:,.2f} from Extra Fund.')
        except (ValueError, InvalidOperation):
            messages.error(request, 'Invalid amount entered.')

    return redirect('management:driver_list')

@transaction.atomic
@login_required
def pay_debt(request, driver_id):
    driver = get_object_or_404(Driver, id=driver_id)

    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount'))
            if amount <= 0:
                messages.error(request, 'Amount must be positive.')
            elif amount > driver.debt:
                messages.error(request, 'Payment amount exceeds debt.')
            else:
                driver.debt -= amount
                driver.save()
                
                # Log the transaction
                UserActivityLog.objects.create(
                    user=request.user,
                    action='pay_debt',
                    details=f'Paid ₱{amount:,.2f} towards debt for driver {driver.driver_name}'
                )
                
                messages.success(request, f'Successfully paid ₱{amount:,.2f} towards debt.')
        except (ValueError, InvalidOperation):
            messages.error(request, 'Invalid amount entered.')

    return redirect('management:driver_list')

@user_passes_test(is_admin)
@login_required
def update_remittance_amount(request):
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', '200'))
            if amount <= 0:
                return JsonResponse({'success': False, 'error': 'Amount must be greater than 0'})
            
            remittance_amount, created = RemittanceAmount.objects.get_or_create(pk=1)
            remittance_amount.amount = amount
            remittance_amount.updated_by = request.user
            remittance_amount.save()
            
            return JsonResponse({'success': True, 'amount': str(amount)})
        except (InvalidOperation, ValueError) as e:
            return JsonResponse({'success': False, 'error': 'Invalid amount'})
    
    remittance_amount = RemittanceAmount.objects.first()
    if not remittance_amount:
        remittance_amount = RemittanceAmount.objects.create(amount=200.00)
    
    return JsonResponse({'amount': str(remittance_amount.amount)})

@login_required
def confirm_remittance(request, unit_id):
    unit = get_object_or_404(Unit, id=unit_id)
    if not unit.driver:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'No driver assigned to this unit'})
        messages.error(request, 'No driver assigned to this unit')
        return redirect('management:unit_list')
    driver = unit.driver

    # Get the current remittance amount
    remittance_amount = RemittanceAmount.objects.first()
    if not remittance_amount:
        remittance_amount = RemittanceAmount.objects.create(amount=200.00)
    required = remittance_amount.amount

    if request.method == 'POST':
        try:
            with transaction.atomic():
                cash_amount = Decimal(request.POST.get('cash_amount', '0') or '0').quantize(Decimal('0.00'))
                if cash_amount < 0:
                    raise ValueError("Negative values are not allowed")

                # Calculate shortage or excess
                savings_used = Decimal('0.00')
                if cash_amount >= required:
                    excess = (cash_amount - required).quantize(Decimal('0.00'))
                    # Add excess to extra fund
                    driver.savings += excess
                else:
                    shortage = (required - cash_amount).quantize(Decimal('0.00'))
                    # Use as much extra fund as possible to cover shortage
                    if driver.savings >= shortage:
                        savings_used = shortage
                        driver.savings -= shortage
                    else:
                        savings_used = driver.savings
                        debt_incurred = (shortage - savings_used).quantize(Decimal('0.00'))
                        driver.debt += debt_incurred
                        driver.savings = Decimal('0.00')

                # If there's existing debt, try to pay it from extra fund
                if driver.debt > 0 and driver.savings > 0:
                    if driver.savings >= driver.debt:
                        driver.savings -= driver.debt
                        driver.debt = Decimal('0.00')
                    else:
                        driver.debt -= driver.savings
                        driver.savings = Decimal('0.00')

                # Find the latest open Remittance record for this unit and driver
                remittance = Remittance.objects.filter(unit=unit, driver=driver, released_at__isnull=True).order_by('-date').first()
                if remittance:
                    remittance.remit_amount = cash_amount
                    remittance.savings_amount = savings_used
                    remittance.released_at = timezone.now()
                    remittance.save()
                else:
                    # Fallback: create a new remittance if not found (should not happen)
                    remittance = Remittance.objects.create(
                        unit=unit,
                        driver=driver,
                        remit_amount=cash_amount,
                        savings_amount=savings_used,
                        date=timezone.now(),
                        released_at=timezone.now()
                    )

                driver.save()
                unit.driver = None
                unit.status = 'stand_by'
                unit.save()

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': f'Remittance processed for {unit.unit_PO}'})
                messages.success(request, f'Remittance processed for {unit.unit_PO}')
                return redirect('management:unit_list')

        except (ValueError, InvalidOperation) as e:
            error_msg = f'Invalid amount: {str(e)}'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
        except Exception as e:
            logger.error(f"Remittance error: {str(e)}", exc_info=True)
            error_msg = 'Error processing remittance'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)

        return redirect('management:unit_list')

@user_passes_test(is_admin)
@login_required
def accounts(request):
    """Admin accounts view showing all user profiles and system status."""
    all_users = UserProfile.objects.all()
    total_users = all_users.count()
    active_users = all_users.filter(status='active').count()
    inactive_users = total_users - active_users

    # Get system statistics
    total_drivers = Driver.objects.count()
    active_drivers = Driver.objects.filter(status='active').count()
    total_units = Unit.objects.count()
    active_units = Unit.objects.filter(status='in_use').count()
    in_use_units = Unit.objects.filter(status='in_use').count()
    maintenance_units = Unit.objects.filter(status='under_maintenance').count()
    out_of_service_units = Unit.objects.filter(status='out_of_service').count()

    # Get driver data for overview with pagination
    drivers = Driver.objects.all().order_by('driver_name')
    paginator_drivers = Paginator(drivers, 10)
    page_number_drivers = request.GET.get('page_drivers', 1)
    drivers_page = paginator_drivers.get_page(page_number_drivers)
    total_savings = drivers.aggregate(Sum('savings'))['savings__sum'] or 0
    total_debt = drivers.aggregate(Sum('debt'))['debt__sum'] or 0

    # --- Delinquent driver logic ---
    from .models import RemittanceAmount, Remittance
    delinquent_driver_ids = set()
    remittance_amount_obj = RemittanceAmount.objects.first()
    required_amount = float(remittance_amount_obj.amount) if remittance_amount_obj else 200.0
    for driver in drivers:
        debt = float(driver.debt or 0)
        remittances = Remittance.objects.filter(driver=driver)
        total_remit = sum(float(r.remit_amount or 0) for r in remittances)
        count_remit = remittances.count()
        avg_remit = (total_remit / count_remit) if count_remit > 0 else 0
        if debt > 1000 or (required_amount > 0 and avg_remit < 0.5 * required_amount):
            delinquent_driver_ids.add(driver.id)
    # --- End delinquent logic ---

    # Get unit data for overview with pagination
    units = Unit.objects.all().select_related('driver').prefetch_related('damage_parts').order_by('unit_PO')
    paginator_units = Paginator(units, 10)
    page_number_units = request.GET.get('page_units', 1)
    units_page = paginator_units.get_page(page_number_units)

    # Get activity logs
    activity_logs = UserActivityLog.objects.all().order_by('-timestamp')
    paginator_logs = Paginator(activity_logs, 8)
    page_number_logs = request.GET.get('page_logs', 1)
    activity_logs = paginator_logs.get_page(page_number_logs)

    # Get the current remittance amount
    remittance_amount = RemittanceAmount.objects.first()
    if not remittance_amount:
        remittance_amount = RemittanceAmount.objects.create(amount=200.00)

    context = {
        'all_users': all_users,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'total_drivers': total_drivers,
        'active_drivers': active_drivers,
        'total_units': total_units,
        'active_units': active_units,
        'in_use_units': in_use_units,
        'maintenance_units': maintenance_units,
        'out_of_service_units': out_of_service_units,
        'remittance_amount': remittance_amount,
        'drivers': drivers_page,
        'units': units_page,
        'total_savings': total_savings,
        'total_debt': total_debt,
        'activity_logs': activity_logs,
        'delinquent_driver_ids': list(delinquent_driver_ids),
    }

    return render(request, 'admin/accounts.html', context)

@user_passes_test(is_admin)
@login_required
def toggle_user_status(request, user_id):
    user = get_object_or_404(User, id=user_id)
    profile, created = UserProfile.objects.get_or_create(user=user)
    # Toggle between active and inactive
    if profile.status == 'active':
        profile.status = 'inactive'
        action = 'deactivated'
    else:
        profile.status = 'active'
        action = 'activated'
        # Set default role to Staff when activating
        user.is_staff = True
        user.is_superuser = False
        user.save()
    profile.save()
    # Create activity log after status change
    UserActivityLog.objects.create(
        user=request.user,
        action='status_change',
        details=f"Changed status of {user.username} to {profile.status}"
    )
    messages.success(request, f'User {action} successfully')
    return redirect('management:accounts')

@user_passes_test(is_admin)
@login_required
def user_activity_logs(request):
    activity_logs = UserActivityLog.objects.all().order_by('-timestamp')
    paginator = Paginator(activity_logs, 8)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin/user_history.html', {
        'activity_logs': page_obj
    })

@user_passes_test(is_admin)
@login_required
def toggle_driver_status(request, driver_id):
    driver = get_object_or_404(Driver, id=driver_id)

    if request.method == 'POST':
        # Get the new status from the form
        new_status = request.POST.get('status')
        if new_status in dict(Driver.STATUS_CHOICES):
            old_status = driver.status
            driver.status = new_status
            driver.save()
            # Log driver status change
            UserActivityLog.objects.create(
                user=request.user,
                action='toggle_driver_status',
                details=f"Changed status of driver {driver.driver_name} (ID: {driver.id}) from {old_status} to {driver.status}"
            )
            messages.success(request, f"Driver {driver.driver_name} status updated to {driver.get_status_display()}")
        else:
            messages.error(request, "Invalid status selected.")

    return redirect('management:accounts')

@user_passes_test(is_admin)
@login_required
def admin_dashboard(request):
    """Admin dashboard view showing all user profiles and system status."""
    all_users = UserProfile.objects.all()
    total_users = all_users.count()
    active_users = all_users.filter(status='active').count()
    inactive_users = total_users - active_users

    # Get system statistics
    total_drivers = Driver.objects.count()
    active_drivers = Driver.objects.filter(status='active').count()
    total_units = Unit.objects.count()
    active_units = Unit.objects.filter(status='in_use').count()

    # Get remittance amount
    remittance_amount = RemittanceAmount.objects.first()
    if not remittance_amount:
        remittance_amount = RemittanceAmount.objects.create(amount=200.00)

    context = {
        'all_users': all_users,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'total_drivers': total_drivers,
        'active_drivers': active_drivers,
        'total_units': total_units,
        'active_units': active_units,
        'remittance_amount': remittance_amount,
    }
    return render(request, 'admin/admin_dashboard.html', context)

@user_passes_test(is_admin)
@login_required
def activity_logs_pagination(request):
    """Handle activity logs pagination via AJAX."""
    activity_logs = UserActivityLog.objects.all().order_by('-timestamp')
    paginator = Paginator(activity_logs, 8)
    page_number = request.GET.get('page')
    activity_logs = paginator.get_page(page_number)

    # Render the template to HTML
    html = render(request, 'admin/activity_logs_partial.html', {
        'activity_logs': activity_logs,
    }).content.decode('utf-8')

    return JsonResponse({
        'html': html,
        'has_next': activity_logs.has_next(),
        'has_previous': activity_logs.has_previous(),
        'current_page': activity_logs.number,
        'total_pages': activity_logs.paginator.num_pages,
    })

@login_required
def update_extra_fund(request, driver_id):
    if request.method == 'POST':
        try:
            driver = Driver.objects.get(id=driver_id)
            action = request.POST.get('action')
            amount = Decimal(request.POST.get('amount', 0))

            if amount <= 0:
                return JsonResponse({
                    'success': False,
                    'message': 'Amount must be greater than 0'
                })

            if action == 'deposit':
                driver.savings += amount
                message = f'Successfully deposited ₱{amount:.2f} to extra fund'
            elif action == 'withdraw':
                if driver.savings < amount:
                    return JsonResponse({
                        'success': False,
                        'message': 'Insufficient extra fund balance'
                    })
                driver.savings -= amount
                message = f'Successfully withdrew ₱{amount:.2f} from extra fund'
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid action'
                })

            driver.save()

            # Log the transaction
            UserActivityLog.objects.create(
                user=request.user,
                action='update_extra_fund',
                details=f'{message} for driver {driver.driver_name}'
            )

            return JsonResponse({
                'success': True,
                'message': message
            })

        except Driver.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Driver not found'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            })

    return JsonResponse({
        'success': False,
        'message': 'Invalid request method'
    })

@login_required
def driver_transactions(request, driver_id):
    try:
        driver = Driver.objects.get(id=driver_id)
        from decimal import Decimal
        from .models import RemittanceAmount
        # Get all transactions related to this driver
        transactions = []
        # Get the required remittance amount
        remittance_amount_obj = RemittanceAmount.objects.first()
        required_amount = float(remittance_amount_obj.amount) if remittance_amount_obj else 200.0
        # Get remittance transactions (for excess and shortage)
        remittances = Remittance.objects.filter(driver=driver).order_by('date')
        for remit in remittances:
            #  log excess to extra fund if remit_amount > required
            if float(remit.remit_amount) > required_amount:
                excess = float(remit.remit_amount) - required_amount
                transactions.append({
                    'date': remit.created_at.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Excess Remittance to Extra Fund',
                    'amount': excess,
                    'balance_at_time': None
                })
            # Log extra fund used (deduction)
            if float(remit.savings_amount) > 0:
                transactions.append({
                    'date': remit.created_at.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Extra Fund Used',
                    'amount': -float(remit.savings_amount),
                    'balance_at_time': None
                })
            # Log remittance shortage (debt incurred) if any
            shortage = required_amount - float(remit.remit_amount)
            if shortage > 0:
                # If savings_amount < shortage, the rest is debt
                savings_used = float(remit.savings_amount)
                debt_incurred = shortage - savings_used
                if debt_incurred > 0:
                    transactions.append({
                        'date': remit.created_at.strftime('%Y-%m-%d %H:%M'),
                        'type': 'Remittance Shortage (Debt Incurred)',
                        'amount': -debt_incurred,
                        'balance_at_time': None
                    })
        # Get extra fund transactions
        extra_fund_logs = UserActivityLog.objects.filter(
            action='update_extra_fund',
            details__contains=f'driver {driver.driver_name}'
        ).order_by('timestamp')
        for log in extra_fund_logs:
            if 'deposited' in log.details:
                amount = float(log.details.split('₱')[1].split()[0])
                transactions.append({
                    'date': log.timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Extra Fund Deposit',
                    'amount': amount,
                    'balance_at_time': None
                })
            elif 'withdrew' in log.details:
                amount = float(log.details.split('₱')[1].split()[0])
                transactions.append({
                    'date': log.timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Extra Fund Withdrawal',
                    'amount': -amount,
                    'balance_at_time': None
                })
        # Include debt payments (pay_debt action)
        debt_payment_logs = UserActivityLog.objects.filter(
            action='pay_debt',
            details__contains=f'driver {driver.driver_name}'
        ).order_by('timestamp')
        for log in debt_payment_logs:
            # Extract amount from details (should be positive)
            try:
                amount = float(log.details.split('₱')[1].split()[0])
                transactions.append({
                    'date': log.timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Debt Payment',
                    'amount': amount,  # Positive amount for payment
                    'balance_at_time': None
                })
            except (IndexError, ValueError):
                continue
        # Sort transactions by date in ascending order (oldest to newest)
        transactions.sort(key=lambda x: x['date'])
        # Calculate running balance
        running_balance = 0
        for transaction in transactions:
            running_balance += transaction['amount']
            transaction['balance_at_time'] = running_balance
        #  show the last 10 transactions (most recent 10)
        transactions = transactions[-10:]
        # Always start opening_balance at zero for all drivers
        opening_balance = 0
        return JsonResponse({
            'success': True,
            'transactions': transactions,
            'opening_balance': opening_balance
        })
    except Driver.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Driver not found'
        })
    except Exception as e:
        logger.error(f"Error in driver_transactions: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@login_required
def manage_damage_parts(request):
    """View for managing damage parts and reporting unit damages."""
    if request.method == 'POST':
        unit_id = request.POST.get('unit_id')
        damage_description = request.POST.get('damage_description')
        
        if not unit_id or not damage_description:
            messages.error(request, 'Please provide both unit and damage description.')
            return redirect('management:manage_damage_parts')
        
        try:
            unit = get_object_or_404(Unit, id=unit_id)
            
            # Create damage report
            damage_report = DamageReport.objects.create(
                unit=unit,
                description=damage_description,
                previous_status=unit.status
            )
            # Log damage report
            UserActivityLog.objects.create(
                user=request.user,
                action='report_damage',
                details=f"Reported damage for unit {unit.unit_PO} (ID: {unit.id}): {damage_description}"
            )
            # Update unit status to under maintenance if not already
            if unit.status != 'under_maintenance':
                unit.previous_status = unit.status
                unit.status = 'under_maintenance'
                unit.save()
            
            messages.success(request, f'Damage reported successfully for unit {unit.unit_PO}')
            return redirect('management:manage_damage_parts')
            
        except Exception as e:
            logger.error(f"Error reporting damage: {str(e)}", exc_info=True)
            messages.error(request, f'Error reporting damage: {str(e)}')
            return redirect('management:manage_damage_parts')
    
    # GET request - display the form and active damages
    available_units = Unit.objects.filter(status__in=['stand_by', 'in_use'])
    active_damages = DamageReport.objects.filter(is_fixed=False).select_related('unit')
    
    return render(request, 'manage_damage_parts.html', {
        'available_units': available_units,
        'active_damages': active_damages,
    })

@login_required
def mark_fixed(request, damage_id):
    """Mark a damage report as fixed and restore unit status."""
    if request.method == 'POST':
        try:
            damage_report = get_object_or_404(DamageReport, id=damage_id)
            unit = damage_report.unit
            # Mark damage as fixed
            damage_report.is_fixed = True
            from django.utils import timezone
            damage_report.fixed_date = timezone.now()  # Set the fixed date
            damage_report.save()
            # Log fixing damage
            UserActivityLog.objects.create(
                user=request.user,
                action='fix_damage',
                details=f"Marked damage as fixed for unit {unit.unit_PO} (ID: {unit.id})"
            )
            # Restore unit status if it was under maintenance
            if unit.status == 'under_maintenance':
                unit.status = unit.previous_status or 'stand_by'
                unit.previous_status = None
                unit.save()
            messages.success(request, f'Damage marked as fixed for unit {unit.unit_PO}')
        except Exception as e:
            logger.error(f"Error marking damage as fixed: {str(e)}", exc_info=True)
            messages.error(request, f'Error marking damage as fixed: {str(e)}')
    return redirect('management:manage_damage_parts')

@login_required
def unit_statistics(request, unit_id):
    try:
        unit = Unit.objects.get(id=unit_id)
        
        # Get remittance statistics
        remittances = Remittance.objects.filter(unit=unit)
        remittance_stats = {
            'total_count': remittances.count(),
            'total_amount': remittances.aggregate(total=Sum('remit_amount'))['total'] or 0,
            'average_amount': remittances.aggregate(avg=Avg('remit_amount'))['avg'] or 0,
            'last_remittance': remittances.order_by('-date').first().date.isoformat() if remittances.exists() else None
        }
        
        # Get maintenance statistics
        maintenance_reports = DamageReport.objects.filter(unit=unit)
        
        # Get reports from the last month
        one_month_ago = timezone.now() - timedelta(days=30)
        monthly_reports = maintenance_reports.filter(reported_date__gte=one_month_ago)
        monthly_count = monthly_reports.count()
        
        logger.info(f"Unit {unit.unit_PO} has {monthly_count} maintenance reports in the last 30 days")
        
        maintenance_stats = {
            'total_count': maintenance_reports.count(),
            'monthly_count': monthly_count,  # Add count of reports in the last month
            'last_maintenance': maintenance_reports.order_by('-reported_date').first().reported_date.isoformat() if maintenance_reports.exists() else None,
            'current_status': unit.get_status_display()
        }
        
        return JsonResponse({
            'remittance_stats': remittance_stats,
            'maintenance_stats': maintenance_stats
        })
    except Unit.DoesNotExist:
        return JsonResponse({'error': 'Unit not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting unit statistics: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def driver_statistics(request, driver_id):
    """Get statistics for a specific driver."""
    try:
        driver = get_object_or_404(Driver, id=driver_id)
        
        # Get remittance statistics
        remittances = Remittance.objects.filter(driver=driver)
        total_count = remittances.count()
        total_amount = remittances.aggregate(total=Sum('remit_amount'))['total'] or 0
        average_amount = total_amount / total_count if total_count > 0 else 0
        last_remittance = remittances.order_by('-date').first()
        
        # Get unit statistics
        units = Unit.objects.filter(driver=driver)
        total_units = units.count()
        current_unit = units.filter(status='in_use').first()  # Changed from 'active' to 'in_use' to match model choices
        
        return JsonResponse({
            'remittance_stats': {
                'total_count': total_count,
                'total_amount': str(total_amount),
                'average_amount': str(average_amount),
                'last_remittance': last_remittance.date.strftime('%Y-%m-%d') if last_remittance else None
            },
            'unit_stats': {
                'total_units': total_units,
                'current_unit': current_unit.unit_PO if current_unit else None,
                'status': driver.get_status_display(),
                'extra_fund': str(driver.savings),
                'debt': str(driver.debt)
            }
        })
    except Exception as e:
        logger.error(f"Error in driver_statistics: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': str(e)
        }, status=500)

@login_required
def driver_statement(request, driver_id):
    """Get statement of account for a specific driver."""
    try:
        driver = get_object_or_404(Driver, id=driver_id)
        
        # Get all transactions related to this driver
        transactions = []
        
        # Get remittance transactions
        remittances = Remittance.objects.filter(driver=driver).order_by('-date')
        for remit in remittances:
            # Add remittance transaction
            transactions.append({
                'date': remit.date.strftime('%Y-%m-%d %H:%M'),
                'type': 'Remittance',
                'amount': float(remit.remit_amount),
                'balance': float(driver.savings)
            })
            
            # Add savings deduction if any
            if remit.savings_amount > 0:
                transactions.append({
                    'date': remit.date.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Extra Fund Used',
                    'amount': -float(remit.savings_amount),
                    'balance': float(driver.savings)
                })

        # Get extra fund transactions
        extra_fund_logs = UserActivityLog.objects.filter(
            action='update_extra_fund',
            details__contains=f'driver {driver.driver_name}'
        ).order_by('-timestamp')
        
        for log in extra_fund_logs:
            if 'deposited' in log.details:
                amount = float(log.details.split('₱')[1].split()[0])
                transactions.append({
                    'date': log.timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Extra Fund Deposit',
                    'amount': amount,
                    'balance': float(driver.savings)
                })
            elif 'withdrew' in log.details:
                amount = float(log.details.split('₱')[1].split()[0])
                transactions.append({
                    'date': log.timestamp.strftime('%Y-%m-%d %H:%M'),
                    'type': 'Extra Fund Withdrawal',
                    'amount': -amount,
                    'balance': float(driver.savings)
                })

        # Get debt payments
        debt_payments = UserActivityLog.objects.filter(
            Q(action='pay_debt') | Q(action='update_extra_fund'),
            details__contains=f'driver {driver.driver_name}'
        ).order_by('-timestamp')
        
        for payment in debt_payments:
            if 'paid' in payment.details.lower() or 'debt' in payment.details.lower():
                try:
                    amount = float(payment.details.split('₱')[1].split()[0])
                    transactions.append({
                        'date': payment.timestamp.strftime('%Y-%m-%d %H:%M'),
                        'type': 'Debt Payment',
                        'amount': -amount,
                        'balance': float(driver.debt)
                    })
                except (IndexError, ValueError):
                    logger.error(f"Error parsing debt payment amount from log: {payment.details}")
                    continue

        # Sort transactions by date
        transactions.sort(key=lambda x: x['date'], reverse=True)

        return JsonResponse({
            'success': True,
            'transactions': transactions[:10]  # Return last 10 transactions
        })

    except Driver.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Driver not found'
        })
    except Exception as e:
        logger.error(f"Error in driver_statement: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@require_POST
@login_required
def assign_device(request):
    """Assign or remove a device IMEI to a unit and create/link it in Flespi."""
    try:
        unit_id = request.POST.get('unit_id')
        device_imei = request.POST.get('device_imei', '').strip()
        
        if not unit_id:
            return JsonResponse({'success': False, 'error': 'Missing unit_id'})
        
        unit = get_object_or_404(Unit, id=unit_id)
        
        #  allow superusers or staff to assign/remove devices
        if not request.user.is_superuser and not request.user.is_staff:
            return JsonResponse({'success': False, 'error': 'Permission denied'})
        
        # If device_imei is empty, remove device
        if not device_imei:
            unit.device_imei = None
            unit.flespi_device_id = None
            unit.save()
            logger.info(f"Device removed from unit {unit.unit_PO} (ID: {unit.id})")
            return JsonResponse({'success': True, 'message': 'Device removed successfully'})
        
        # Validate IMEI (should be numeric and appropriate length)
        if not device_imei.isdigit() or len(device_imei) < 8 or len(device_imei) > 16:
            logger.warning(f"Invalid IMEI format: {device_imei} for unit {unit.unit_PO}")
            return JsonResponse({
                'success': False, 
                'error': 'Invalid IMEI format. Must be 8-16 digits.'
            })
        
        # Set the IMEI regardless of whether we can create a Flespi device
        # This ensures we at least have the IMEI stored
        logger.info(f"Setting IMEI {device_imei} for unit {unit.unit_PO} (ID: {unit.id})")
        unit.device_imei = device_imei
        unit.save(update_fields=['device_imei'])
        
        # Initialize Flespi API
        flespi = FlespiAPI(settings.FLESPI_TOKEN)
        logger.info(f"Assigning device using Flespi API with MOCK_MODE: {flespi.MOCK_MODE}")
        
        # Now try to find or create the device in Flespi
        device_id = flespi.ensure_device_exists(unit)
        
        if device_id:
            logger.info(f"Device ID assigned: {device_id}")
            
            # Save the device ID to the unit
            unit.flespi_device_id = device_id
            unit.save(update_fields=['flespi_device_id'])
            
            # Log the activity
            UserActivityLog.objects.create(
                user=request.user,
                action='assign_device',
                details=f"Assigned device IMEI {device_imei} to unit {unit.unit_PO} (ID: {device_id})"
            )
            
            # This is a successful assignment
            return JsonResponse({
                'success': True, 
                'message': 'Device assigned successfully',
                'device_id': device_id,
                'device_imei': device_imei,
                'mock_mode': flespi.MOCK_MODE
            })
        else:
            # Fallback to mock mode if we couldn't create a real device
            # This allows the system to continue working with simulated data
            logger.warning(f"Failed to create real Flespi device for IMEI {device_imei}, falling back to mock mode")
            
            # Create a deterministic mock ID based on the IMEI
            import hashlib
            hash_obj = hashlib.md5(device_imei.encode())
            mock_id = f"mock-{hash_obj.hexdigest()[:8]}"
            
            # Save the mock device ID
            unit.flespi_device_id = mock_id
            unit.save(update_fields=['flespi_device_id'])
            
            # Log the activity
            UserActivityLog.objects.create(
                user=request.user,
                action='assign_mock_device',
                details=f"Assigned mock device for IMEI {device_imei} to unit {unit.unit_PO} (ID: {mock_id})"
            )
            
            # This is a partial success - we have the IMEI and a mock device ID
            return JsonResponse({
                'success': True, 
                'message': 'Device assigned in mock mode due to API issues',
                'device_id': mock_id,
                'device_imei': device_imei,
                'mock_mode': True,
                'warning': 'Using mock data - real Flespi device could not be created'
            })
        
    except requests.RequestException as e:
        logger.error(f"Network error with Flespi API: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': f"API communication error: {str(e)}"})
    except Exception as e:
        logger.error(f"Error assigning device: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': f"Assignment error: {str(e)}"})

def unit_position_history(request, unit_id):
    """
    REST API endpoint to get position history for a unit directly from Flespi
    instead of relying on local database.
    """
    try:
        unit = get_object_or_404(Unit, id=unit_id)
        if not unit.flespi_device_id:
            return JsonResponse({
                'success': False,
                'error': 'Unit does not have a device assigned'
            })
        hours = int(request.GET.get('hours', 24))
        cache_key = f"device_history_{unit.flespi_device_id}_h{hours}"
        positions = cache.get(cache_key)
        if positions is None:
            flespi = FlespiAPI(settings.FLESPI_TOKEN)
            positions = flespi.get_device_history(unit.flespi_device_id, hours=hours)
            cache.set(cache_key, positions, 300)  # Cache for 5 minutes
        # Always build position_data and return, regardless of cache
        position_data = []
        for pos in positions or []:
            lat = pos.get('position.latitude')
            lng = pos.get('position.longitude')
            ts = pos.get('timestamp')
            if lat is None or lng is None or ts is None:
                continue
            position_data.append({
                'latitude': lat,
                'longitude': lng,
                'speed': pos.get('position.speed', 0),
                'timestamp': ts,
                'datetime': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            })
        return JsonResponse({
            'success': True,
            'unit': unit.unit_PO,
            'positions': position_data
        })
    except ValueError as e:
        return JsonResponse({
            'success': False, 
            'error': f'Invalid parameter: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f"Error getting unit position history: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
@require_GET
@login_required
def live_unit_positions(request):
    """
    REST API endpoint to get real-time positions for all units with devices
    directly from Flespi API without relying on local database
    """
    try:
        # Get all units with device IDs
        units = Unit.objects.exclude(flespi_device_id__isnull=True).exclude(flespi_device_id='')
        
        if not units:
            return JsonResponse({
                "success": True,
                "units": [],
                "message": "No units with device IDs found",
                "mock_mode": False
            })
        
        # Initialize the Flespi API client
        flespi = FlespiAPI(settings.FLESPI_TOKEN)
        
        # Force real data mode - never use mock data
        flespi.__class__.MOCK_MODE = False
        logger.info("Using real data mode for position tracking")
            
        # Get telemetry for all devices at once - more efficient than individual calls
        # Extract device IDs from units
        device_ids = [unit.flespi_device_id for unit in units]
        
        # Get telemetry for all devices with device IDs
        all_telemetry = flespi.get_all_devices_telemetry(device_ids)
        
        # Process results
        unit_locations = []
        for unit in units:
            if not unit.flespi_device_id:
                continue
            device_data = all_telemetry.get(unit.flespi_device_id, {}) if all_telemetry else {}
            latitude = None
            longitude = None
            timestamp = None
            speed = 0
            direction = 0
            battery = None
            if 'latitude' in device_data:
                latitude = device_data.get('latitude')
                longitude = device_data.get('longitude')
                timestamp = device_data.get('timestamp')
                speed = device_data.get('speed', 0)
                direction = device_data.get('direction', 0)
                battery = device_data.get('battery', None)
            else:
                latitude = device_data.get("position.latitude", {}).get("value")
                longitude = device_data.get("position.longitude", {}).get("value")
                timestamp = device_data.get("position.latitude", {}).get("timestamp")
                speed = device_data.get("position.speed", {}).get("value", 0)
                direction = device_data.get("position.direction", {}).get("value", 0)
                battery = device_data.get("battery.level", {}).get("value", None)
            if latitude is None or longitude is None:
                cache_key = f"device_history_{unit.flespi_device_id}"
                history = cache.get(cache_key)
                if history is None:
                    flespi = FlespiAPI(settings.FLESPI_TOKEN)
                    history = flespi.get_device_history(unit.flespi_device_id, hours=24)
                    cache.set(cache_key, history, 300)  # Cache for 5 minutes
                if history:
                    latest = history[-1]
                    latitude = latest.get('position.latitude')
                    longitude = latest.get('position.longitude')
                    timestamp = latest.get('timestamp')
                    speed = latest.get('position.speed', 0)
                    direction = latest.get('position.direction')
                    battery = latest.get('battery.level')
                else:
                    # Try to fetch from DevicePosition model (CSV import)
                    pos = DevicePosition.objects.filter(unit=unit).order_by('-timestamp').first()
                    if pos:
                        latitude = pos.latitude
                        longitude = pos.longitude
                        timestamp = int(pos.timestamp.timestamp())
                        speed = pos.speed
                        direction = None
                        battery = None
                    else:
                        continue
            unit_locations.append({
                "unit_id": unit.id,
                "unit_PO": unit.unit_PO,
                "driver": unit.driver.driver_name if unit.driver else None,
                "latitude": latitude,
                "longitude": longitude,
                "speed": speed,
                "timestamp": timestamp,
                "battery": battery,
                "direction": direction,
            })
        if not unit_locations:
            logger.warning("No valid position data found for any units")
        return JsonResponse({
            "success": True,
            "units": unit_locations,
            "count": len(unit_locations),
            "mock_mode": False
        })
        
    except Exception as e:
        logger.error(f"Error in live_unit_positions: {e}", exc_info=True)
        return JsonResponse({
            "success": False,
            "error": str(e),
            "units": [],
            "mock_mode": False
        }, status=500)

@login_required
def get_live_unit_position(request, unit_id):
    """
    REST API endpoint to get real-time position from Flespi API for a specific unit
    """
    from .models import Unit

    try:
        unit = Unit.objects.get(id=unit_id)
        if not unit.flespi_device_id:
            return JsonResponse({'success': False, 'error': 'No Flespi device ID assigned.'}, status=400)

        # Initialize the Flespi API client
        flespi = FlespiAPI(settings.FLESPI_TOKEN)
        
        # Get real-time telemetry directly from Flespi
        telemetry = flespi.get_telemetry(unit.flespi_device_id)
        
        if telemetry and telemetry.get("latitude") is not None and telemetry.get("longitude") is not None:
        # Return comprehensive telemetry data
            return JsonResponse({
            'success': True,
            'unit_id': unit.id,
            'unit_po': unit.unit_PO,
            'driver': unit.driver.driver_name if unit.driver else None,
            'position': {
                'latitude': telemetry.get("latitude"),
                'longitude': telemetry.get("longitude"),
                'speed': telemetry.get("speed", 0),
                'altitude': telemetry.get("altitude"),
                'direction': telemetry.get("direction"),
                'hdop': telemetry.get("hdop"),
                'satellites': telemetry.get("satellites")
            },
            'battery': telemetry.get("battery"),
            'timestamp': telemetry.get("timestamp")
        })
        else:
            # Try to get the latest position from history (last 24 hours)
            history = flespi.get_device_history(unit.flespi_device_id, hours=24)
            if history:
                latest = history[-1]
                return JsonResponse({
                    'success': True,
                    'unit_id': unit.id,
                    'unit_po': unit.unit_PO,
                    'driver': unit.driver.driver_name if unit.driver else None,
                    'position': {
                        'latitude': latest.get('position.latitude'),
                        'longitude': latest.get('position.longitude'),
                        'speed': latest.get('position.speed', 0),
                        'altitude': latest.get('position.altitude'),
                        'direction': latest.get('position.direction'),
                        'hdop': latest.get('position.hdop'),
                        'satellites': latest.get('position.satellites')
                    },
                    'battery': latest.get('battery.level'),
                    'timestamp': latest.get('timestamp')
                })
            else:
                return JsonResponse({'success': False, 'error': 'No position data available'}, status=404)

    except Unit.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Unit not found'}, status=404)
    except requests.RequestException as e:
        logger.error(f"Flespi API error: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    except Exception as e:
        logger.error(f"Unexpected error in get_live_unit_position: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'Internal server error'}, status=500)

@login_required
def flespi_api_diagnostics(request):
    """
    Diagnostic view to test Flespi API connectivity and provide detailed information
    about any issues.  accessible to superusers.
    """
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Access denied'}, status=403)
        
    results = {
        'api_status': 'unknown',
        'tests': [],
        'configuration': {
            'base_url': None,
            'token': None,
            'token_valid': None
        }
    }
    
    try:
        # Initialize the Flespi API client
        token = settings.FLESPI_TOKEN
        if not token:
            results['tests'].append({
                'name': 'API Token',
                'status': 'error',
                'message': 'No Flespi API token configured'
            })
            results['api_status'] = 'error'
            results['configuration']['token'] = 'Not configured'
            return JsonResponse(results)
            
        # Mask token for security but show enough to identify
        if len(token) > 8:
            masked_token = token[:4] + '*' * (len(token) - 8) + token[-4:]
        else:
            masked_token = '****' + token[-4:] if len(token) >= 4 else '*****'
            
        results['configuration']['token'] = masked_token
        
        flespi = FlespiAPI(token)
        results['configuration']['base_url'] = flespi.BASE_URL
        
        # Test basic connectivity
        connection_valid = flespi._verify_connection()
        results['configuration']['token_valid'] = connection_valid
        
        results['tests'].append({
            'name': 'API Connection',
            'status': 'success' if connection_valid else 'error',
            'message': 'Connection successful' if connection_valid else 'Failed to connect to API'
        })
        
        if connection_valid:
            # Test 1: Check if we can get the list of devices
            try:
                url = f"{flespi.BASE_URL}/devices"
                resp = requests.get(url, headers=flespi.headers)
                resp.raise_for_status()
                devices = resp.json().get('result', [])
                
                results['tests'].append({
                    'name': 'Get Devices',
                    'status': 'success',
                    'message': f'Found {len(devices)} devices'
                })
                
                # If we have devices, try getting telemetry for the first one
                if devices:
                    device_id = devices[0].get('id')
                    
                    # Test 2: Get telemetry for a single device
                    try:
                        telemetry = flespi.get_telemetry(device_id)
                        if telemetry:
                            results['tests'].append({
                                'name': 'Get Device Telemetry',
                                'status': 'success',
                                'message': f'Successfully retrieved telemetry for device {device_id}'
                            })
                        else:
                            results['tests'].append({
                                'name': 'Get Device Telemetry',
                                'status': 'warning',
                                'message': f'No telemetry data available for device {device_id}'
                            })
                    except Exception as e:
                        results['tests'].append({
                            'name': 'Get Device Telemetry',
                            'status': 'error',
                            'message': str(e)
                        })
                    
                    # Test 3: Try the batch telemetry endpoint
                    try:
                        url = f"{flespi.BASE_URL}/devices/all/telemetry"
                        resp = requests.get(url, headers=flespi.headers)
                        resp.raise_for_status()
                        results['tests'].append({
                            'name': 'Batch Telemetry API',
                            'status': 'success',
                            'message': 'Batch telemetry endpoint is available'
                        })
                    except Exception as e:
                        results['tests'].append({
                            'name': 'Batch Telemetry API',
                            'status': 'error',
                            'message': f'Batch telemetry endpoint error: {str(e)}'
                        })
                    
                    # Test 4: Try the get_all_devices_telemetry method that includes fallback
                    try:
                        # Extract device IDs from units
                        device_ids = [unit.flespi_device_id for unit in units]
                        
                        # Get telemetry for all devices with device IDs
                        all_telemetry = flespi.get_all_devices_telemetry(device_ids)
                        results['tests'].append({
                            'name': 'Get All Devices Telemetry',
                            'status': 'success',
                            'message': f'Retrieved telemetry for {len(all_telemetry)} devices'
                        })
                    except Exception as e:
                        results['tests'].append({
                            'name': 'Get All Devices Telemetry',
                            'status': 'error',
                            'message': str(e)
                        })
                else:
                    results['tests'].append({
                        'name': 'Get Device Telemetry',
                        'status': 'skipped',
                        'message': 'No devices available to test telemetry'
                    })
            except Exception as e:
                results['tests'].append({
                    'name': 'Get Devices',
                    'status': 'error',
                    'message': str(e)
                })
            
            # Determine overall status
            if all(test['status'] == 'success' for test in results['tests']):
                results['api_status'] = 'healthy'
            elif any(test['status'] == 'error' for test in results['tests']):
                results['api_status'] = 'error'
            else:
                results['api_status'] = 'warning'
        else:
            results['api_status'] = 'error'
            
    except Exception as e:
        results['api_status'] = 'error'
        results['error'] = str(e)
    
    return JsonResponse(results)

@login_required
def flespi_diagnostics_page(request):
    """Render the Flespi API diagnostics page."""
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to access this page")
        return redirect('management:tracking')
    
    # Test the API connection with the configured token
    connection_test = FlespiAPI.test_connection(settings.FLESPI_TOKEN)
    
    context = {
        'api_status': connection_test,
        'flespi_token': settings.FLESPI_TOKEN,
        'mock_mode': FlespiAPI.MOCK_MODE,
        'base_url': FlespiAPI.BASE_URL
    }
    
    return render(request, 'admin/flespi_diagnostics.html', context)

@login_required
def tracking(request):
    """View for tracking units on a map with real-time position updates."""
    # Get all units with device IDs
    units = Unit.objects.exclude(flespi_device_id__isnull=True).exclude(flespi_device_id='').all()
    
    # Always use real data, never mock mode
    enable_mock = False
    
    # Get initial unit data (without positions)
    unit_data = []
    for unit in units:
        unit_data.append({
                "unit_id": unit.id,
                "unit_PO": unit.unit_PO,
                "driver": unit.driver.driver_name if unit.driver else None,
                "device_id": unit.flespi_device_id
        })
    
    context = {
        "unit_data": json.dumps(unit_data),
        "refresh_interval": 10000,  # 10 seconds refresh interval
        "flespi_token": settings.FLESPI_TOKEN,  # Pass token for optional direct WebSocket connection
        "mock_mode": enable_mock  # Tell the template if we're in mock mode
    }
    
    return render(request, "management/tracking.html", context)

@login_required
def assign_driver(request):
    """Assign a driver to a unit and create a Remittance record for the rental start."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    try:
        unit_id = request.POST.get('unit_id')
        driver_id = request.POST.get('driver_id')

        if not unit_id or not driver_id:
            return JsonResponse({'success': False, 'error': 'Missing required fields'})

        unit = get_object_or_404(Unit, id=unit_id)
        driver = get_object_or_404(Driver, id=driver_id)

        # Check if unit is out of service
        if unit.status == 'out_of_service':
            return JsonResponse({
                'success': False,
                'error': 'Cannot assign driver to a unit that is out of service'
            })

        # Check if driver is already assigned to another unit
        if Unit.objects.filter(driver=driver, status='in_use').exists():
            return JsonResponse({
                'success': False,
                'error': 'Driver is already assigned to another unit'
            })

        # Update unit
        unit.driver = driver
        unit.status = 'in_use'
        unit.save()

        # Create a new Remittance record for the start of rental
        Remittance.objects.create(
            unit=unit,
            driver=driver,
            date=timezone.now()
        )

        # Log the activity
        UserActivityLog.objects.create(
            user=request.user,
            action='assign_driver',
            details=f"Assigned driver {driver.driver_name} to unit {unit.unit_PO}"
        )

        return JsonResponse({
            'success': True,
            'message': f'Driver {driver.driver_name} assigned to unit {unit.unit_PO}'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def get_remittance_amount(request):
    """Get the current remittance amount for non-admin users."""
    remittance_amount = RemittanceAmount.objects.first()
    if not remittance_amount:
        remittance_amount = RemittanceAmount.objects.create(amount=200.00)
    return JsonResponse({'amount': str(remittance_amount.amount)})

@login_required
def unit_overview_pagination(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    page = request.GET.get('page', 1)
    
    # Define status priority for sorting
    status_priority = {
        'in_use': 1,
        'stand_by': 2,
        'under_maintenance': 3,
        'out_of_service': 4
    }
    
    # Get all units and sort them
    units = Unit.objects.all().select_related('driver')
    units = sorted(units, key=lambda x: (status_priority.get(x.status, 5), x.unit_PO))
    
    paginator = Paginator(units, 10)  # Show 10 units per page
    
    try:
        units_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        units_page = paginator.page(1)
    
    context = {
        'units': units_page,
        'active_units': Unit.objects.filter(status='in_use').count(),
        'in_use_units': Unit.objects.filter(status='in_use').count(),
        'maintenance_units': Unit.objects.filter(status='under_maintenance').count(),
        'out_of_service_units': Unit.objects.filter(status='out_of_service').count(),
    }
    
    html = render_to_string('management/includes/unit_overview_table.html', context, request=request)
    return JsonResponse({'html': html})

@login_required
def driver_overview_pagination(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    page = request.GET.get('page', 1)
    
    # Get all drivers and sort them by status and name
    drivers = Driver.objects.all()
    drivers = sorted(drivers, key=lambda x: (0 if x.status == 'active' else 1, x.driver_name.lower()))
    
    # --- Delinquent driver logic ---
    from .models import RemittanceAmount, Remittance
    delinquent_driver_ids = set()
    remittance_amount_obj = RemittanceAmount.objects.first()
    required_amount = float(remittance_amount_obj.amount) if remittance_amount_obj else 200.0
    for driver in drivers:
        debt = float(driver.debt or 0)
        remittances = Remittance.objects.filter(driver=driver)
        total_remit = sum(float(r.remit_amount or 0) for r in remittances)
        count_remit = remittances.count()
        avg_remit = (total_remit / count_remit) if count_remit > 0 else 0
        if debt > 1000 or (required_amount > 0 and avg_remit < 0.5 * required_amount):
            delinquent_driver_ids.add(driver.id)
    # --- End delinquent logic ---
    
    paginator = Paginator(drivers, 10)  # Show 10 drivers per page
    
    try:
        drivers_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        drivers_page = paginator.page(1)
    
    context = {
        'drivers': drivers_page,
        'active_drivers': Driver.objects.filter(status='active').count(),
        'total_savings': Driver.objects.aggregate(total=Sum('savings'))['total'] or 0,
        'total_debt': Driver.objects.aggregate(total=Sum('debt'))['total'] or 0,
        'delinquent_driver_ids': list(delinquent_driver_ids),
    }
    
    html = render_to_string('management/includes/driver_overview_table.html', context, request=request)
    return JsonResponse({'html': html})

@login_required
def import_position_history(request, unit_id):
    """Import position history from a CSV file"""
    from datetime import datetime
    import csv
    from io import TextIOWrapper
    
    # Get the unit
    unit = get_object_or_404(Unit, id=unit_id)
    
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        
        # Check if it's a CSV file
        if not csv_file.name.endswith('.csv'):
            messages.error(request, 'Please upload a CSV file')
            return redirect('management:unit_position_history', unit_id=unit_id)
        
        # Process the file
        try:
            # Decode the file
            csv_file = TextIOWrapper(csv_file.file, encoding='utf-8')
            reader = csv.DictReader(csv_file)
            
            # Check required fields
            required_fields = ['timestamp', 'latitude', 'longitude']
            csv_fields = reader.fieldnames
            
            if not all(field in csv_fields for field in required_fields):
                messages.error(request, 'CSV file must include timestamp, latitude, and longitude columns')
                return redirect('management:unit_position_history', unit_id=unit_id)
            
            # Import the positions
            positions_added = 0
            positions_skipped = 0
            for row in reader:
                try:
                    # Parse the timestamp (try multiple formats)
                    timestamp = None
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%m/%d/%Y %H:%M:%S', '%d/%m/%Y %H:%M:%S']:
                        try:
                            timestamp = datetime.strptime(row['timestamp'], fmt)
                            break
                        except ValueError:
                            continue
                    
                    if not timestamp:
                        # Try Unix timestamp
                        try:
                            timestamp = datetime.fromtimestamp(float(row['timestamp']))
                        except ValueError:
                            positions_skipped += 1
                            continue
                    
                    # Create the position record
                    DevicePosition.objects.create(
                        unit=unit,
                        latitude=float(row['latitude']),
                        longitude=float(row['longitude']),
                        speed=float(row.get('speed', 0)),
                        timestamp=timestamp
                    )
                    positions_added += 1
                    
                except (ValueError, KeyError) as e:
                    logger.error(f"Error importing position row: {e}")
                    positions_skipped += 1
            
            # Show success message
            if positions_added > 0:
                messages.success(request, f'Successfully imported {positions_added} positions ({positions_skipped} skipped)')
            else:
                messages.warning(request, f'No positions were imported. {positions_skipped} rows were invalid.')
            
        except Exception as e:
            logger.error(f"Error importing CSV: {e}", exc_info=True)
            messages.error(request, f'Error importing CSV: {str(e)}')
        
        return redirect('management:unit_position_history', unit_id=unit_id)
    
    # If GET request, show the upload form
    context = {
        'unit': unit
    }
    return render(request, 'management/import_positions.html', context)

@user_passes_test(is_admin)
@login_required
@require_POST
def update_user_roles(request, user_id):
    """Update is_staff and is_superuser roles for a user.  one role can be set at a time."""
    user = get_object_or_404(User, id=user_id)
    is_staff = bool(request.POST.get('is_staff'))
    is_superuser = bool(request.POST.get('is_superuser'))
    if is_superuser:
        user.is_superuser = True
        user.is_staff = False
    elif is_staff:
        user.is_staff = True
        user.is_superuser = False
    else:
        user.is_staff = False
        user.is_superuser = False
    user.save()
    # Log user role update
    UserActivityLog.objects.create(
        user=request.user,
        action='change_user_role',
        details=f"Changed roles for {user.username}: is_staff={user.is_staff}, is_superuser={user.is_superuser}"
    )
    messages.success(request, f"Roles updated for {user.username}.")
    return redirect('management:accounts')