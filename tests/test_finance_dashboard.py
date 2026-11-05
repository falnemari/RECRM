import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_finance_dashboard_kpis_agent26():
    """Verify that Agent-26 (user-19, ACCOUNTANT) sees live, non-zero financial metrics."""
    with TestClient(app) as client:
        res = client.get('/api/v1/reports/finance-dashboard', headers={'X-User-ID': 'user-19'})
        assert res.status_code == 200
        data = res.json()['data']
        kpis = data['kpis']
        
        # Verify non-zero live metrics
        assert kpis['actual_collected_cash'] > 0
        assert kpis['audited_araboun_amount'] > 0
        assert kpis['audited_araboun_count'] >= 1
        assert kpis['brokerage_fees_invoiced'] > 0
        assert kpis['rental_inflows'] > 0
        assert kpis['vat_amount'] > 0
        assert kpis['rett_amount'] > 0
        assert kpis['payable_broker_commissions'] > 0
        assert kpis['disbursed_broker_commissions'] > 0

        # Verify ledgers structure
        ledgers = data['ledgers']
        assert 'invoices' in ledgers
        assert 'commissions' in ledgers
        assert 'payments' in ledgers
        assert len(ledgers['invoices']) > 0
        assert len(ledgers['commissions']) > 0
        assert len(ledgers['payments']) > 0

        # Verify live pulse
        assert 'live_pulse' in data
        assert len(data['live_pulse']) > 0

def test_finance_dashboard_scoping():
    """Verify finance dashboard respects GLOBAL, BRANCH, and OWN scopes."""
    with TestClient(app) as client:
        # Global scope
        res_global = client.get('/api/v1/reports/finance-dashboard?scope=GLOBAL', headers={'X-User-ID': 'user-51'})
        assert res_global.status_code == 200
        d_global = res_global.json()['data']
        assert d_global['scope_info']['scope'] == 'GLOBAL'

        # Branch scope
        res_branch = client.get('/api/v1/reports/finance-dashboard?scope=BRANCH&branch_id=branch-3', headers={'X-User-ID': 'user-19'})
        assert res_branch.status_code == 200
        d_branch = res_branch.json()['data']
        assert d_branch['scope_info']['scope'] == 'BRANCH'

def test_managerial_kpis_finance_role_view():
    """Verify managerial KPIs adapt to Article 7 Finance equations when role_view=FINANCE."""
    with TestClient(app) as client:
        res = client.get('/api/v1/reports/managerial-kpis?role_view=FINANCE', headers={'X-User-ID': 'user-19'})
        assert res.status_code == 200
        data = res.json()['data']

        assert data['role_perspective']['is_finance'] is True
        assert data['role_perspective']['active_role_view'] == 'FINANCE'

        # Deposit Audit SLA (Eq 7.1)
        assert data['deposit_audit_sla'] is not None
        assert data['deposit_audit_sla']['sla_type'] == 'DEPOSIT_AUDIT_SLA'
        assert data['deposit_audit_sla']['compliance_rate'] > 0

        # Cash Collection Efficiency (Eq 7.2)
        assert data['cash_collection_efficiency'] is not None
        assert data['cash_collection_efficiency']['kpi_type'] == 'CASH_COLLECTION_EFFICIENCY'
        assert data['cash_collection_efficiency']['conversion_rate'] > 0

        # Commission Payout SLA (Eq 7.4)
        assert data['commission_payout_sla'] is not None
        assert data['commission_payout_sla']['kpi_type'] == 'COMMISSION_PAYOUT_SLA'
        assert data['commission_payout_sla']['conversion_rate'] > 0

def test_edit_reference_number():
    """Verify PATCH /api/v1/finance/reference updates reference numbers cleanly."""
    with TestClient(app) as client:
        # 1. Update invoice reference
        res = client.patch(
            '/api/v1/finance/reference/invoice/inv-358',
            json={'reference_number': 'INV-202611-3470-OWNR-V2'},
            headers={'X-User-ID': 'user-19'}
        )
        assert res.status_code == 200
        assert res.json()['data']['updated']['invoice_number'] == 'INV-202611-3470-OWNR-V2'

        # Revert back to original
        res_rev = client.patch(
            '/api/v1/finance/reference/invoice/inv-358',
            json={'reference_number': 'INV-202611-3470-OWNR'},
            headers={'X-User-ID': 'user-19'}
        )
        assert res_rev.status_code == 200
        assert res_rev.json()['data']['updated']['invoice_number'] == 'INV-202611-3470-OWNR'

def test_contracts_rental_visibility_and_search():
    """Verify contracts endpoint correctly returns rental contracts with customer and unit details."""
    with TestClient(app) as client:
        # Search rental contract TEN-202611-2415
        res = client.get('/api/v1/contracts?search=TEN-202611-2415', headers={'X-User-ID': 'user-19'})
        assert res.status_code == 200
        json_data = res.json()
        assert 'data' in json_data
        contracts = json_data['data']
        assert len(contracts) >= 1
        c = next((item for item in contracts if item['contract_number'] == 'TEN-202611-2415'), None)
        assert c is not None
        assert c['contract_type'] == 'RENT'
        assert c['customer_name'] == 'Kheder Alnemari'
        assert c['unit_number'] == 'Unit-10-20-2'
        assert float(c['contract_value']) == 25000.0
        assert c['status'] == 'ACTIVE'

        # Filter by status ACTIVE
        res_active = client.get('/api/v1/contracts?status=ACTIVE', headers={'X-User-ID': 'user-19'})
        assert res_active.status_code == 200
        active_list = res_active.json()['data']
        assert any(item['contract_number'] == 'TEN-202611-2415' for item in active_list)

        # Filter by contract_type RENT
        res_rent = client.get('/api/v1/contracts?contract_type=RENT', headers={'X-User-ID': 'user-19'})
        assert res_rent.status_code == 200
        rent_list = res_rent.json()['data']
        assert all(item['contract_type'] == 'RENT' for item in rent_list)
        assert any(item['contract_number'] == 'TEN-202611-2415' for item in rent_list)

def test_payments_search_and_rent_collections():
    """Verify unified payments endpoint returns both sales payments and rent collection installments."""
    with TestClient(app) as client:
        res = client.get('/api/v1/payments?search=TEN-202611-2415', headers={'X-User-ID': 'user-19'})
        assert res.status_code == 200
        payments = res.json()['data']
        assert len(payments) == 2
        statuses = {p['status'] for p in payments}
        assert statuses == {'PAID', 'DUE'}
        for p in payments:
            assert float(p['amount_due']) == 12500.0
            assert p['contract_number'] == 'TEN-202611-2415'
            assert p['customer_name'] == 'Kheder Alnemari'
            assert p['unit_number'] == 'Unit-10-20-2'
            assert p['method'] == 'RENT_INSTALLMENT'

def test_task_completion_details_and_document_rendering():
    """Verify task completion details endpoint and document HTML rendering for completed lease task task-16903."""
    with TestClient(app) as client:
        # 1. Test task completion details endpoint
        res = client.get('/api/v1/tasks/task-16903/completion-details', headers={'X-User-ID': 'user-19'})
        assert res.status_code == 200
        data = res.json()['data']

        assert data['task']['task_id'] == 'task-16903'
        assert data['task']['status'] == 'COMPLETED'
        assert data['tenancy']['tenancy_id'] == 'tenancy-364'
        assert data['contract']['contract_number'] == 'TEN-202611-2415'
        assert data['tenancy']['bank_iban'] == 'SA0380000000608010167890'
        assert data['tenancy']['bank_name'] == 'مصرف الراجحي'
        assert data['tenancy']['bank_beneficiary'] == 'عبدالله محمد السبيعي'
        assert 'شبكة إيجار' in data['tenancy']['maintenance_terms']
        assert data['tenancy']['payment_frequency'] == 'SEMI_ANNUAL'
        assert len(data['installments']) == 2
        assert len(data['documents']) >= 1
        assert data['activity']['subject'] == 'الإيجار — تفعيل عقد الإيجار وتسليم الوحدة'

        # 2. Test contracts router returns enriched tenancy fields
        res_con = client.get('/api/v1/contracts?search=TEN-202611-2415', headers={'X-User-ID': 'user-19'})
        assert res_con.status_code == 200
        con_list = res_con.json()['data']
        assert len(con_list) >= 1
        con = con_list[0]
        assert con['bank_iban'] == 'SA0380000000608010167890'
        assert con['bank_name'] == 'مصرف الراجحي'
        assert con['bank_beneficiary'] == 'عبدالله محمد السبيعي'
        assert 'شبكة إيجار' in con['maintenance_terms']
        assert con['payment_frequency'] == 'SEMI_ANNUAL'

        # 3. Test document HTML endpoint renders complete legal and financial sections
        doc_id = data['documents'][0]['document_id']
        res_doc = client.get(f'/api/v1/documents/{doc_id}/html', headers={'X-User-ID': 'user-19'})
        assert res_doc.status_code == 200
        html = res_doc.text
        assert 'SA0380000000608010167890' in html
        assert 'مصرف الراجحي' in html
        assert 'عبدالله محمد السبيعي' in html
        assert 'وفق المعيار المعتمد في شبكة إيجار' in html
        assert 'جدول دفعات وأقساط العقد المعتمد' in html
        assert '12,500' in html

def test_filtered_financial_schedule_and_payments_for_deal():
    """Verify loading payments and filtering financial schedule for deal lead-1793470988 / opportunity-1793471156."""
    with TestClient(app) as client:
        # 1. Unfiltered payments table loads cleanly without 500 error
        res_all = client.get('/api/v1/payments', headers={'X-User-ID': 'user-19'})
        assert res_all.status_code == 200
        assert res_all.json()['meta']['total'] > 0

        # 2. Payments filtered by opportunity_id
        res_deal_pay = client.get('/api/v1/payments?opportunity_id=opportunity-1793471156', headers={'X-User-ID': 'user-19'})
        assert res_deal_pay.status_code == 200
        pay_items = res_deal_pay.json()['data']
        assert len(pay_items) == 2
        for p in pay_items:
            assert float(p['amount_due']) == 12500.0
            assert p['contract_number'] == 'TEN-202611-2415'
            assert p['customer_name'] == 'Kheder Alnemari'

        # 3. Financial schedule filtered for deal in Dashboard
        res_fin = client.get(
            '/api/v1/reports/financial-schedule?scope=GLOBAL&lead_id=lead-1793470988&opportunity_id=opportunity-1793471156',
            headers={'X-User-ID': 'user-51'}
        )
        assert res_fin.status_code == 200
        fin_data = res_fin.json()['data']
        # 2 rent collections (25,000 SAR) + 2 statutory fee invoices (718.75 SAR customer + 125.00 SAR owner)
        assert fin_data['summary']['total_items'] >= 2
        assert fin_data['summary']['total_dues_amount'] >= 25000.0
        assert fin_data['summary']['total_collected_amount'] == 12500.0
        item_types = {item['item_type_code'] for item in fin_data['items']}
        assert 'RENT_COLLECTION' in item_types
        for item in fin_data['items']:
            assert item['customer_name'] == 'Kheder Alnemari'
            assert item['lead_id'] == 'lead-1793470988'
            assert item['opportunity_id'] == 'opportunity-1793471156'

        # 4. Agenda calendar filtered for deal in Dashboard
        res_agenda = client.get(
            '/api/v1/reports/agenda-calendar?scope=GLOBAL&lead_id=lead-1793470988&opportunity_id=opportunity-1793471156&uncompleted_only=false',
            headers={'X-User-ID': 'user-51'}
        )
        assert res_agenda.status_code == 200
        events = res_agenda.json()['data']['events']
        rent_events = [e for e in events if e['event_type'] == 'RENT_COLLECTION']
        assert len(rent_events) == 2
        for ev in rent_events:
            assert ev['lead_id'] == 'lead-1793470988'
            assert ev['opportunity_id'] == 'opportunity-1793471156'
            assert float(ev['amount']) == 12500.0


