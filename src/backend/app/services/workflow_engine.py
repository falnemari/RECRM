"""
RECRM Workflow Engine Service
=============================
Implements the core 4 primitives:
  1. Business Records: Updates status ONLY upon validated, recorded events.
  2. Tasks: Forward-looking directives with SLAs, assigned roles, and anti-duplication protection.
  3. Activities: Immutable historical records of real-world outcomes.
  4. Communications: Recorded only when a message event actually occurs.

Also handles customer deduplication and first-contact SLA enforcement.
"""

import re
import json
import hashlib
import random
import logging
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timezone, timedelta, date
import asyncpg
from app.database import get_next_id

logger = logging.getLogger("recrm.workflow_engine")


def normalize_saudi_phone(phone: Optional[str]) -> Optional[str]:
    """
    Standardize Saudi phone numbers into canonical E.164-like format: +9665XXXXXXXX
    Handles:
      '0500558590'   -> '+966500558590'
      '500558590'    -> '+966500558590'
      '966500558590' -> '+966500558590'
      '+966500558590'-> '+966500558590'
    """
    if not phone:
        return None
    # Strip spaces, dashes, parentheses
    cleaned = re.sub(r"[\s\-\(\)]", "", str(phone).strip())
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    
    if cleaned.startswith("05") and len(cleaned) == 10:
        return f"+966{cleaned[1:]}"
    elif cleaned.startswith("5") and len(cleaned) == 9:
        return f"+966{cleaned}"
    elif cleaned.startswith("9665") and len(cleaned) == 12:
        return f"+{cleaned}"
    elif cleaned.startswith("+966"):
        return cleaned
    
    # Fallback to stripped original with plus if international
    return f"+{cleaned}" if not phone.startswith("+") else phone


class WorkflowEngine:

    @staticmethod
    async def archive_workflow_document(
        conn: asyncpg.Connection,
        doc_type_code: str,
        file_name: str,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        task_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        contract_id: Optional[str] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Securely archives an official workflow document into the `documents` table and access log.
        """
        try:
            dt = await conn.fetchrow("SELECT document_type_id, name FROM document_types WHERE code = $1", doc_type_code.upper())
            if not dt:
                return None
            
            org = await conn.fetchrow("SELECT organization_id FROM organizations LIMIT 1")
            org_id = org["organization_id"] if org else "organization-1"
            
            # Check existing document for this task or opportunity
            existing_id = None
            if task_id:
                existing_id = await conn.fetchval(
                    "SELECT document_id FROM documents WHERE task_id = $1 AND document_type_id = $2",
                    task_id, dt["document_type_id"]
                )
            
            meta_json = json.dumps(metadata) if metadata else None
            now_dt = datetime.now(timezone.utc)
            today_d = date.today()
            
            active_u = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' LIMIT 1")
            u_id = user_id or active_u or "user-27"
            
            if existing_id:
                await conn.execute(
                    """
                    UPDATE documents
                    SET notes = $1, metadata = $2::jsonb
                    WHERE document_id = $3
                    """,
                    notes, meta_json, existing_id
                )
                return existing_id
            
            doc_id = await get_next_id(conn, "documents", "document")
            storage_uri = f"/vault/workflows/{doc_type_code.lower()}/{file_name}"
            file_hash = hashlib.sha256(f"{doc_id}-{file_name}-{now_dt.isoformat()}".encode()).hexdigest()
            
            await conn.execute(
                """
                INSERT INTO documents (
                    document_id, organization_id, document_type_id, customer_id, unit_id, contract_id,
                    lead_id, opportunity_id, task_id, notes, metadata,
                    file_name, storage_uri, file_hash, version_no, issued_at, expires_at,
                    status, uploaded_by_user_id, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, 1, $15, $16, 'ACTIVE', $17, $18)
                """,
                doc_id, org_id, dt["document_type_id"], customer_id, unit_id, contract_id,
                lead_id, opportunity_id, task_id, notes, meta_json,
                file_name, storage_uri, file_hash, today_d, None, u_id, now_dt
            )
            
            await conn.execute(
                """
                INSERT INTO document_access_log (
                    document_id, user_id, action, accessed_at, ip_address
                ) VALUES ($1, $2, 'WORKFLOW_ARCHIVE', NOW(), '127.0.0.1')
                """,
                doc_id, u_id
            )
            return doc_id
        except Exception as e:
            logger.error(f"Failed to archive workflow document {doc_type_code}: {e}", exc_info=True)
            return None

    @staticmethod
    async def find_or_create_customer(
        conn: asyncpg.Connection,
        org_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        mobile: Optional[str] = None,
        email: Optional[str] = None,
        national_id: Optional[str] = None,
        company_name: Optional[str] = None,
        customer_type: str = "INDIVIDUAL"
    ) -> Tuple[str, bool, Dict[str, Any]]:
        """
        Comprehensive Multi-Factor Deduplication Check:
        Checks for existing customer across 3 core unique vectors:
          1. National ID / Iqama / Commercial Registration ID (exact or SHA256 hash)
          2. Phone / Mobile (normalized, exact, or trailing 9 digits)
          3. Email (case-insensitive)
        If found:
          Reuses existing customer record, auto-enriches any missing fields, and returns (customer_id, is_duplicate=True, customer_info).
        If not found:
          Creates new customer record and returns (customer_id, is_duplicate=False, customer_info).
        """
        clean_nid = re.sub(r"[\s\-_]", "", national_id.strip()) if (national_id and national_id.strip()) else None
        nid_hash = hashlib.sha256(clean_nid.encode()).hexdigest() if clean_nid else None

        norm_mobile = normalize_saudi_phone(mobile)
        raw_digits = re.sub(r"\D", "", mobile or "")
        tail_9 = raw_digits[-9:] if len(raw_digits) >= 9 else raw_digits

        clean_email = email.strip().lower() if (email and email.strip()) else None

        existing = None
        matched_by = None
        matched_val = None

        # Priority 1: Check by National ID / Iqama / Commercial Registration ID
        if clean_nid:
            existing = await conn.fetchrow(
                """
                SELECT customer_id, first_name, last_name, company_name, mobile, email, national_id_hash, status, created_at
                FROM customers
                WHERE organization_id = $1 AND (
                    national_id_hash = $2 OR
                    national_id_hash = $3 OR
                    LOWER(national_id_hash) = LOWER($2)
                )
                ORDER BY created_at ASC
                LIMIT 1
                """,
                org_id, clean_nid, nid_hash
            )
            if existing:
                matched_by = "رقم الهوية / السجل (National ID / CR)"
                matched_val = clean_nid

        # Priority 2: Check by Phone / Mobile
        if not existing and tail_9:
            existing = await conn.fetchrow(
                """
                SELECT customer_id, first_name, last_name, company_name, mobile, email, national_id_hash, status, created_at
                FROM customers
                WHERE organization_id = $1 AND (
                    mobile = $2 OR
                    mobile = $3 OR
                    RIGHT(REGEXP_REPLACE(mobile, '[^0-9]', '', 'g'), 9) = $4
                )
                ORDER BY created_at ASC
                LIMIT 1
                """,
                org_id, mobile, norm_mobile, tail_9
            )
            if existing:
                matched_by = "رقم الجوال (Mobile Number)"
                matched_val = mobile

        # Priority 3: Check by Email
        if not existing and clean_email:
            existing = await conn.fetchrow(
                """
                SELECT customer_id, first_name, last_name, company_name, mobile, email, national_id_hash, status, created_at
                FROM customers
                WHERE organization_id = $1 AND LOWER(TRIM(email)) = $2
                ORDER BY created_at ASC
                LIMIT 1
                """,
                org_id, clean_email
            )
            if existing:
                matched_by = "البريد الإلكتروني (Email Address)"
                matched_val = clean_email

        # If duplicate detected, enrich missing profile fields and return existing record
        if existing:
            full_name = f"{existing['first_name'] or ''} {existing['last_name'] or ''}".strip() or existing['company_name'] or "Customer"
            logger.info(f"Duplicate customer detected: Reusing {existing['customer_id']} ({full_name}) matched by {matched_by}: {matched_val}")

            # Auto-enrich missing fields on existing customer
            enrich_sets = []
            enrich_params = []
            p_idx = 1
            if not existing["email"] and clean_email:
                enrich_sets.append(f"email = ${p_idx}")
                enrich_params.append(clean_email)
                p_idx += 1
            if not existing["mobile"] and norm_mobile:
                enrich_sets.append(f"mobile = ${p_idx}")
                enrich_params.append(norm_mobile)
                p_idx += 1
            if not existing["national_id_hash"] and nid_hash:
                enrich_sets.append(f"national_id_hash = ${p_idx}")
                enrich_params.append(nid_hash)
                p_idx += 1

            if enrich_sets:
                enrich_params.append(existing["customer_id"])
                await conn.execute(
                    f"UPDATE customers SET {', '.join(enrich_sets)}, updated_at = NOW() WHERE customer_id = ${p_idx}",
                    *enrich_params
                )

            return (
                existing["customer_id"],
                True,
                {
                    "customer_id": existing["customer_id"],
                    "full_name": full_name,
                    "mobile": existing["mobile"] or norm_mobile,
                    "email": existing["email"] or clean_email,
                    "status": existing["status"],
                    "matched_by": matched_by,
                    "matched_value": matched_val,
                    "created_at": existing["created_at"]
                }
            )

        # Create new customer
        new_cust_id = await get_next_id(conn, "customers", "customer")
        full_name = f"{first_name or 'New'} {last_name or 'Customer'}".strip() if customer_type == "INDIVIDUAL" else (company_name or "Company")

        await conn.execute(
            """
            INSERT INTO customers (
                customer_id, organization_id, customer_type, first_name, last_name,
                company_name, mobile, email, national_id_hash, preferred_language, status, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, 'ar', 'ACTIVE', NOW(), NOW()
            )
            """,
            new_cust_id, org_id, customer_type, first_name or "New", last_name or "Customer",
            company_name, norm_mobile or mobile, clean_email, nid_hash
        )

        return (
            new_cust_id,
            False,
            {
                "customer_id": new_cust_id,
                "full_name": full_name,
                "mobile": norm_mobile or mobile,
                "email": clean_email,
                "status": "ACTIVE"
            }
        )

    @staticmethod
    async def find_branch_and_manager_for_city(
        conn: asyncpg.Connection,
        city_id: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Locates the appropriate branch and its active Branch Manager (SALES_MANAGER).
        Rules:
          1. If city_id is provided, match active branch for that city.
          2. If not found or city_id is None, fallback to Head Office / Main Branch (BR-001 / branch-3) or first active branch.
          3. Returns (branch_id, manager_user_id).
        """
        branch_id = None
        if city_id:
            branch_id = await conn.fetchval(
                "SELECT branch_id FROM branches WHERE city_id = $1 AND status = 'ACTIVE' LIMIT 1",
                city_id
            )

        if not branch_id:
            branch_id = await conn.fetchval(
                "SELECT branch_id FROM branches WHERE branch_code = 'BR-001' OR branch_id = 'branch-3' LIMIT 1"
            ) or await conn.fetchval(
                "SELECT branch_id FROM branches WHERE status = 'ACTIVE' ORDER BY branch_id LIMIT 1"
            )

        manager_user_id = None
        if branch_id:
            manager_user_id = await conn.fetchval(
                """
                SELECT u.user_id 
                FROM users u 
                JOIN user_roles ur ON u.user_id = ur.user_id 
                JOIN roles r ON ur.role_id = r.role_id 
                WHERE u.branch_id = $1 AND r.role_code = 'SALES_MANAGER' AND u.status = 'ACTIVE'
                ORDER BY u.created_at ASC
                LIMIT 1
                """,
                branch_id
            )

        if not manager_user_id:
            # Fallback to any active sales manager in the system
            manager_user_id = await conn.fetchval(
                """
                SELECT u.user_id 
                FROM users u 
                JOIN user_roles ur ON u.user_id = ur.user_id 
                JOIN roles r ON ur.role_id = r.role_id 
                WHERE r.role_code = 'SALES_MANAGER' AND u.status = 'ACTIVE'
                ORDER BY u.created_at ASC
                LIMIT 1
                """
            )

        return (branch_id, manager_user_id)

    @staticmethod
    async def on_lead_assigned(
        conn: asyncpg.Connection,
        lead_id: str,
        assigned_user_id: str,
        assigner_user_id: Optional[str] = None,
        branch_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handles workflow state when a lead is assigned or reassigned to a sales agent:
          1. Completes any pending TASK_LEAD_ASSIGN for the branch manager.
          2. Spawns or updates TASK_LEAD_FIRST_CONTACT for the assigned sales agent with a 30-minute SLA.
          3. Synchronizes branch_id from user if appropriate.
          4. Records ACT_LEAD_CREATED / assignment activity.
        """
        now_dt = datetime.now(timezone.utc)
        first_contact_due = now_dt + timedelta(minutes=30)

        # 1. Fetch agent and lead info
        agent_row = await conn.fetchrow("SELECT full_name, branch_id FROM users WHERE user_id = $1", assigned_user_id)
        agent_name = agent_row["full_name"] if agent_row else assigned_user_id
        user_branch_id = agent_row["branch_id"] if agent_row else None

        lead = await conn.fetchrow("SELECT customer_id, priority, branch_id, inquiry_type FROM leads WHERE lead_id = $1", lead_id)
        if not lead:
            return {"status": "lead_not_found"}

        customer_id = lead["customer_id"]
        priority = lead["priority"] or "NORMAL"
        inq = (lead["inquiry_type"] or "").upper()
        if inq == "RENT":
            contact_tmpl = "TASK_RENT_LEAD_FIRST_CONTACT"
        elif inq in ("INVEST", "INVESTMENT"):
            contact_tmpl = "TASK_INVEST_LEAD_FIRST_CONTACT"
        else:
            contact_tmpl = "TASK_LEAD_FIRST_CONTACT"

        # 2. Complete open TASK_LEAD_ASSIGN if present
        open_assign_task = await conn.fetchrow(
            """
            SELECT task_id FROM tasks 
            WHERE lead_id = $1 AND template_id = 'TASK_LEAD_ASSIGN' AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            LIMIT 1
            """,
            lead_id
        )
        if open_assign_task:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, open_assign_task["task_id"]
            )

        # Log assignment activity unconditionally for the assigned agent
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_LEAD_ASSIGNED",
            user_id=assigned_user_id,
            customer_id=customer_id,
            lead_id=lead_id,
            outcome="ASSIGNED",
            notes=notes or f"تم تعيين الطلب للوسيط ({agent_name}). تم إسناد مهمة الاتصال الأولي (مهلة 30 دقيقة)."
        )

        # 3. Check for open first contact task (standard, rental, or investment)
        open_contact_task = await conn.fetchrow(
            """
            SELECT task_id FROM tasks 
            WHERE lead_id = $1 AND template_id IN ('TASK_LEAD_FIRST_CONTACT', 'TASK_RENT_LEAD_FIRST_CONTACT', 'TASK_INVEST_LEAD_FIRST_CONTACT') AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            LIMIT 1
            """,
            lead_id
        )
        task_dict = None
        if open_contact_task:
            # Reassign open contact task to new agent
            await conn.execute(
                """
                UPDATE tasks 
                SET assigned_user_id = $1, due_at = $2
                WHERE task_id = $3
                """,
                assigned_user_id, first_contact_due, open_contact_task["task_id"]
            )
            task_dict = dict(open_contact_task)
            task_dict["assigned_user_id"] = assigned_user_id
        else:
            # Check if first contact has already occurred or a first contact task was already completed
            contact_already_done = await conn.fetchval(
                """
                SELECT 1 FROM leads WHERE lead_id = $1 AND (first_contact_at IS NOT NULL OR status IN ('CONTACTED', 'QUALIFIED', 'CONVERTED', 'LOST', 'DISQUALIFIED'))
                UNION
                SELECT 1 FROM tasks WHERE lead_id = $1 AND template_id IN ('TASK_LEAD_FIRST_CONTACT', 'TASK_RENT_LEAD_FIRST_CONTACT', 'TASK_INVEST_LEAD_FIRST_CONTACT') AND status = 'COMPLETED'
                LIMIT 1
                """,
                lead_id
            )
            if not contact_already_done:
                # Spawn fresh contact task for new agent only if not already contacted
                task_dict, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id=contact_tmpl,
                    lead_id=lead_id,
                    customer_id=customer_id,
                    assigned_user_id=assigned_user_id,
                    priority=priority,
                    custom_due_at=first_contact_due
                )

        # 4. Sync lead assigned_user_id, first_contact_due_at and optionally branch_id
        effective_branch_id = branch_id or user_branch_id
        updates = ["assigned_user_id = $1", "first_contact_due_at = $2"]
        params = [assigned_user_id, first_contact_due]
        p_idx = 3
        if effective_branch_id:
            updates.append(f"branch_id = ${p_idx}")
            params.append(effective_branch_id)
            p_idx += 1
        params.append(lead_id)
        await conn.execute(
            f"UPDATE leads SET {', '.join(updates)}, updated_at = NOW() WHERE lead_id = ${p_idx}",
            *params
        )

        return {"status": "assigned", "agent_name": agent_name, "task": task_dict, "activity": activity}

    @staticmethod
    async def spawn_task_from_template(
        conn: asyncpg.Connection,
        template_id: str,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        assigned_user_id: Optional[str] = None,
        priority: Optional[str] = None,
        custom_due_at: Optional[datetime] = None,
        parent_task_id: Optional[str] = None,
        custom_title: Optional[str] = None
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Spawns a standardized task from the template catalog.
        Anti-Duplication / Idempotency Rule:
          Guarantees that an open task for the same template & entity is NOT duplicated.
        Returns:
          (task_dict, is_new: bool)
        """
        # Guarantee priority is adopted from the associated lead unless explicitly overridden
        eff_lead_id = lead_id
        if not eff_lead_id and opportunity_id:
            eff_lead_id = await conn.fetchval(
                "SELECT lead_id FROM opportunities WHERE opportunity_id = $1", opportunity_id
            )
        if eff_lead_id and (not priority or priority == "NORMAL"):
            lead_pri = await conn.fetchval("SELECT priority FROM leads WHERE lead_id = $1", eff_lead_id)
            if lead_pri:
                priority = lead_pri.upper()
        if not priority:
            priority = "NORMAL"

        # 1. Anti-Duplication Check
        existing_task = await conn.fetchrow(
            """
            SELECT task_id, title, due_at, status, priority, assigned_user_id, template_id, parent_task_id
            FROM tasks
            WHERE template_id = $1
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
              AND (
                  ($2::text IS NOT NULL AND lead_id = $2) OR
                  ($3::text IS NOT NULL AND opportunity_id = $3) OR
                  ($2::text IS NULL AND $3::text IS NULL AND $4::text IS NOT NULL AND customer_id = $4)
              )
            LIMIT 1
            """,
            template_id, lead_id, opportunity_id, customer_id
        )

        if existing_task:
            if assigned_user_id and existing_task["assigned_user_id"] != assigned_user_id:
                await conn.execute(
                    "UPDATE tasks SET assigned_user_id = $1 WHERE task_id = $2",
                    assigned_user_id, existing_task["task_id"]
                )
            if parent_task_id and not existing_task["parent_task_id"]:
                await conn.execute(
                    "UPDATE tasks SET parent_task_id = $1 WHERE task_id = $2",
                    parent_task_id, existing_task["task_id"]
                )
            if custom_title and existing_task["title"] != custom_title:
                await conn.execute(
                    "UPDATE tasks SET title = $1 WHERE task_id = $2",
                    custom_title, existing_task["task_id"]
                )
            if priority and existing_task.get("priority") != priority:
                await conn.execute(
                    "UPDATE tasks SET priority = $1 WHERE task_id = $2",
                    priority, existing_task["task_id"]
                )
            t_dict = dict(existing_task)
            if assigned_user_id:
                t_dict["assigned_user_id"] = assigned_user_id
            if parent_task_id:
                t_dict["parent_task_id"] = parent_task_id
            if custom_title:
                t_dict["title"] = custom_title
            if priority:
                t_dict["priority"] = priority
            logger.info(f"Task anti-duplication: Open task {existing_task['task_id']} already exists for template {template_id}. Reusing.")
            return t_dict, False

        # 2. Fetch template details
        tmpl = await conn.fetchrow(
            """
            SELECT template_id, standard_title_ar, standard_title_en, default_sla_minutes, owner_role
            FROM workflow_templates
            WHERE template_id = $1
            """,
            template_id
        )

        standard_title = custom_title or (tmpl["standard_title_ar"] if tmpl else f"Task ({template_id})")
        sla_mins = tmpl["default_sla_minutes"] if tmpl and tmpl["default_sla_minutes"] else 30

        if custom_due_at:
            due_at = custom_due_at
        else:
            due_at = datetime.now(timezone.utc) + timedelta(minutes=sla_mins)

        task_id = await get_next_id(conn, "tasks", "task")

        await conn.execute(
            """
            INSERT INTO tasks (
                task_id, template_id, title, assigned_user_id, customer_id, lead_id,
                opportunity_id, due_at, priority, status, escalation_level, created_at, parent_task_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, 'PENDING', 0, NOW(), $10
            )
            """,
            task_id, template_id, standard_title, assigned_user_id, customer_id, lead_id,
            opportunity_id, due_at, priority, parent_task_id
        )

        new_task = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
        return dict(new_task), True

    @staticmethod
    async def record_activity_from_template(
        conn: asyncpg.Connection,
        template_id: str,
        user_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        task_id: Optional[str] = None,
        outcome: Optional[str] = None,
        notes: Optional[str] = None,
        completed_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Records an immutable Activity representing what actually occurred in the real world.
        """
        tmpl = await conn.fetchrow(
            """
            SELECT standard_title_ar, standard_title_en
            FROM workflow_templates
            WHERE template_id = $1
            """,
            template_id
        )
        subject = tmpl["standard_title_ar"] if tmpl else f"Activity ({template_id})"

        activity_id = await get_next_id(conn, "activities", "activity")
        now_dt = completed_at or datetime.now(timezone.utc)

        act_type_code = "CALL"
        if template_id in ("ACT_VIEWING_SCHEDULED", "ACT_VIEWING_REPORT_SUBMITTED"):
            act_type_code = "VIEWING"
        elif template_id in ("ACT_LEAD_CREATED", "ACT_LEAD_ROUTED"):
            act_type_code = "SYSTEM"
        elif template_id in ("ACT_OFFER_SUBMITTED",):
            act_type_code = "MEETING"
        elif template_id in ("ACT_TASK_REOPENED", "ACT_INVOICE_GENERATED", "ACT_FEE_COLLECTED"):
            act_type_code = "SYSTEM"

        act_type_id = await conn.fetchval(
            "SELECT activity_type_id FROM activity_types WHERE code = $1 LIMIT 1",
            act_type_code
        )

        await conn.execute(
            """
            INSERT INTO activities (
                activity_id, template_id, user_id, customer_id, lead_id, opportunity_id,
                activity_type_id, subject, description, outcome, completed_at, status, created_at, task_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'COMPLETED', NOW(), $12
            )
            """,
            activity_id, template_id, user_id, customer_id, lead_id, opportunity_id,
            act_type_id, subject, notes, outcome, now_dt, task_id
        )

        row = await conn.fetchrow("SELECT * FROM activities WHERE activity_id = $1", activity_id)
        return dict(row)

    @staticmethod
    async def resolve_next_task_template(
        conn: asyncpg.Connection,
        current_template_id: str,
        outcome: Optional[str] = None
    ) -> Optional[str]:
        """
        Dynamically resolves the next task template from database (workflow_templates).
        1. Checks outcome_transitions JSONB for an exact match or normalized upper outcome.
        2. If outcome is not matched or outcome is None, falls back to next_template_id.
        3. Returns None if template is Terminal, Standalone, or outcome maps explicitly to None.
        """
        row = await conn.fetchrow(
            """
            SELECT next_template_id, outcome_transitions 
            FROM workflow_templates 
            WHERE template_id = $1
            """,
            current_template_id
        )
        if not row:
            return None

        next_tmpl = row["next_template_id"]
        outcomes_raw = row["outcome_transitions"]

        if outcomes_raw and outcome:
            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
            norm_outcome = outcome.strip().upper()
            if norm_outcome in outcomes:
                return outcomes[norm_outcome]  # can be None (terminal)
            for k, v in outcomes.items():
                if k.strip().upper() == norm_outcome:
                    return v

        return next_tmpl

    @staticmethod
    async def spawn_next_workflow_task(
        conn: asyncpg.Connection,
        current_task: Dict[str, Any],
        outcome: Optional[str] = None,
        user_id: Optional[str] = None,
        priority: str = "HIGH",
        custom_due_at: Optional[datetime] = None,
        parent_task_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Dynamically resolves and spawns the next task in the workflow graph based on database transitions.
        Returns:
            The spawned task dictionary, or None if current task is terminal or consultative.
        """
        curr_tmpl = current_task.get("template_id")
        if not curr_tmpl:
            return None

        next_tmpl = await WorkflowEngine.resolve_next_task_template(conn, curr_tmpl, outcome)
        if not next_tmpl:
            return None

        assigned_user = current_task.get("assigned_user_id") or user_id
        eff_parent_id = parent_task_id or current_task.get("task_id")

        next_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id=next_tmpl,
            lead_id=current_task.get("lead_id"),
            opportunity_id=current_task.get("opportunity_id"),
            customer_id=current_task.get("customer_id"),
            assigned_user_id=assigned_user,
            priority=priority,
            custom_due_at=custom_due_at,
            parent_task_id=eff_parent_id
        )
        return next_task

    @staticmethod
    async def on_lead_qualified(
        conn: asyncpg.Connection,
        lead_id: str,
        user_id: Optional[str] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        preferred_property_type_id: Optional[str] = None,
        preferred_city_id: Optional[str] = None,
        notes: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage 2 Lead Qualification & Opportunity Conversion:
        Executes atomic business transitions:
          1. Completes any open TASK_LEAD_QUALIFY / TASK_LEAD_FIRST_CONTACT / TASK_LEAD_FOLLOWUP.
          2. Records immutable ACT_LEAD_QUALIFIED activity.
          3. Updates lead status to 'QUALIFIED', and enriches budget/property_type/city if provided.
          4. Creates or updates Opportunity record in stage 'QUALIFIED':
             - Copies all shortlisted units from lead_units to opportunity_units.
          5. Spawns Stage 3 TASK_VIEWING_SCHEDULE (Viewing — Schedule Site Visit) with 24h SLA.
        """
        lead = await conn.fetchrow(
            """
            SELECT customer_id, assigned_user_id, branch_id, status, budget_min, budget_max, 
                   unit_id, preferred_city_id, preferred_property_type_id, inquiry_type
            FROM leads 
            WHERE lead_id = $1
            """,
            lead_id
        )
        if not lead:
            raise ValueError(f"Lead '{lead_id}' not found.")

        effective_user_id = user_id or lead["assigned_user_id"] or "user-51"
        now_dt = datetime.now(timezone.utc)
        inq = (lead["inquiry_type"] or "").upper()
        is_rent = (inq == "RENT")
        is_invest = (inq in ("INVEST", "INVESTMENT"))

        # 1. Complete open qualification or contact tasks for this lead
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE lead_id = $2
              AND template_id IN ('TASK_LEAD_QUALIFY', 'TASK_LEAD_FIRST_CONTACT', 'TASK_RENT_LEAD_FIRST_CONTACT', 'TASK_INVEST_LEAD_FIRST_CONTACT', 'TASK_LEAD_FOLLOWUP')
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            """,
            now_dt, lead_id
        )

        # 2. Update Lead attributes if supplied
        lead_updates = ["status = 'QUALIFIED'", "updated_at = NOW()"]
        lead_params = []
        p_idx = 1
        if budget_min is not None:
            lead_updates.append(f"budget_min = ${p_idx}")
            lead_params.append(budget_min)
            p_idx += 1
        if budget_max is not None:
            lead_updates.append(f"budget_max = ${p_idx}")
            lead_params.append(budget_max)
            p_idx += 1
        if preferred_property_type_id is not None:
            lead_updates.append(f"preferred_property_type_id = ${p_idx}")
            lead_params.append(preferred_property_type_id)
            p_idx += 1
        if preferred_city_id is not None:
            lead_updates.append(f"preferred_city_id = ${p_idx}")
            lead_params.append(preferred_city_id)
            p_idx += 1

        lead_params.append(lead_id)
        await conn.execute(
            f"UPDATE leads SET {', '.join(lead_updates)} WHERE lead_id = ${p_idx}",
            *lead_params
        )

        # 3. Create or Link Opportunity
        existing_opp = await conn.fetchrow(
            "SELECT opportunity_id, stage FROM opportunities WHERE lead_id = $1 LIMIT 1",
            lead_id
        )

        eff_budget_max = budget_max if budget_max is not None else lead["budget_max"]
        eff_budget_min = budget_min if budget_min is not None else lead["budget_min"]
        expected_val = float(eff_budget_max or eff_budget_min or 0.0)

        if lead["unit_id"] and expected_val == 0.0:
            u_price = await conn.fetchval(
                "SELECT COALESCE(asking_price, rent_price, 0) FROM units WHERE unit_id = $1",
                lead["unit_id"]
            )
            if u_price:
                expected_val = float(u_price)

        if not existing_opp:
            opp_id = await get_next_id(conn, "opportunities", "opportunity")
            await conn.execute(
                """
                INSERT INTO opportunities (
                    opportunity_id, lead_id, customer_id, assigned_user_id,
                    stage, expected_value, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, 'QUALIFIED', $5, NOW(), NOW())
                """,
                opp_id, lead_id, lead["customer_id"], effective_user_id, expected_val
            )
        else:
            opp_id = existing_opp["opportunity_id"]
            if existing_opp["stage"] not in ('WON', 'LOST'):
                await conn.execute(
                    """
                    UPDATE opportunities 
                    SET stage = 'QUALIFIED', 
                        expected_value = COALESCE(NULLIF($1, 0), expected_value),
                        assigned_user_id = COALESCE(assigned_user_id, $2),
                        updated_at = NOW() 
                    WHERE opportunity_id = $3
                    """,
                    expected_val, effective_user_id, opp_id
                )

        # 4. Transfer shortlisted units from lead_units to opportunity_units
        await conn.execute(
            """
            INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
            SELECT $1, lu.unit_id, lu.is_primary, COALESCE(un.asking_price, un.rent_price, 0)
            FROM lead_units lu
            JOIN units un ON lu.unit_id = un.unit_id
            WHERE lu.lead_id = $2
            ON CONFLICT (opportunity_id, unit_id) DO NOTHING
            """,
            opp_id, lead_id
        )

        # 5. Record Activity ACT_LEAD_QUALIFIED, ACT_RENT_LEAD_QUALIFIED, or ACT_INVEST_LEAD_QUALIFIED
        if is_invest:
            qual_act_template = "ACT_INVEST_LEAD_QUALIFIED"
            qual_notes = notes or "تم استيفاء معايير تأهيل المستثمر وترقية الطلب لفرصة استثمارية نشطة."
        elif is_rent:
            qual_act_template = "ACT_RENT_LEAD_QUALIFIED"
            qual_notes = notes or "تم استيفاء معايير استئجار الوحدة وترقية الطلب لفرصة إيجارية نشطة."
        else:
            qual_act_template = "ACT_LEAD_QUALIFIED"
            qual_notes = notes or "تم استفاء معايير التأهيل بنجاح وترقية الطلب لفرصة بيعية نشطة."

        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id=qual_act_template,
            user_id=effective_user_id,
            customer_id=lead["customer_id"],
            lead_id=lead_id,
            opportunity_id=opp_id,
            task_id=parent_task_id,
            outcome="QUALIFIED",
            notes=qual_notes,
            completed_at=now_dt
        )

        # 6. Auto-spawn Next Task (Investment vs Rental vs Sales)
        has_primary_unit = await conn.fetchval(
            "SELECT count(*) FROM opportunity_units WHERE opportunity_id = $1 AND is_primary = TRUE",
            opp_id
        )
        qual_outcome = "QUALIFIED_INVESTMENT" if is_invest else ("QUALIFIED_RENT" if is_rent else "QUALIFIED_SALE")
        db_next_tmpl = await WorkflowEngine.resolve_next_task_template(conn, "TASK_LEAD_QUALIFY", qual_outcome)

        if db_next_tmpl:
            if not has_primary_unit and is_rent:
                next_task_template = "TASK_RENT_MATCH_PROPERTIES"
            elif not has_primary_unit and not is_invest:
                next_task_template = "TASK_OPPORTUNITY_MATCH_PROPERTIES"
            else:
                next_task_template = db_next_tmpl
        else:
            if is_invest:
                next_task_template = "TASK_INVEST_CONFIRM_OBJECTIVES"
            elif is_rent:
                next_task_template = "TASK_VIEWING_SCHEDULE" if (has_primary_unit and has_primary_unit > 0) else "TASK_RENT_MATCH_PROPERTIES"
            else:
                next_task_template = "TASK_VIEWING_SCHEDULE" if (has_primary_unit and has_primary_unit > 0) else "TASK_OPPORTUNITY_MATCH_PROPERTIES"

        next_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id=next_task_template,
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=lead["customer_id"],
            assigned_user_id=effective_user_id,
            priority="HIGH",
            parent_task_id=parent_task_id
        )

        return {
            "status": "QUALIFIED",
            "lead_id": lead_id,
            "opportunity_id": opp_id,
            "activity": activity,
            "viewing_task": next_task if next_task_template in ("TASK_VIEWING_SCHEDULE", "TASK_RENT_VIEWING_FOLLOW_UP") else None,
            "matching_task": next_task if next_task_template in ("TASK_OPPORTUNITY_MATCH_PROPERTIES", "TASK_RENT_MATCH_PROPERTIES") else None,
            "invest_task": next_task if is_invest else None,
            "next_task": next_task
        }

    @staticmethod
    async def present_opportunity_properties(
        conn: asyncpg.Connection,
        user_id: str,
        opportunity_id: str,
        unit_ids: Optional[List[str]] = None,
        notes: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage C: Property Matching & Recommendations
        1. Links matched units to opportunity_units.
        2. Closes open TASK_OPPORTUNITY_MATCH_PROPERTIES.
        3. Records ACT_OPPORTUNITY_PROPERTIES_PRESENTED activity.
        4. Records COMM_OPPORTUNITY_RECOMMENDATIONS outbound WhatsApp communication.
        5. Auto-spawns Stage D: TASK_VIEWING_SCHEDULE.
        """
        now_dt = datetime.now(timezone.utc)
        opp = await conn.fetchrow("SELECT * FROM opportunities WHERE opportunity_id = $1", opportunity_id)
        if not opp:
            raise ValueError(f"Opportunity '{opportunity_id}' not found.")

        lead_id = opp["lead_id"]
        customer_id = opp["customer_id"]
        agent_id = opp["assigned_user_id"] or user_id

        is_rent = False
        if lead_id:
            inq = await conn.fetchval("SELECT inquiry_type FROM leads WHERE lead_id = $1", lead_id)
            is_rent = (inq or "").upper() == "RENT"

        # 1. Link provided units
        if unit_ids:
            for idx, uid in enumerate(unit_ids):
                is_prim = (idx == 0)
                await conn.execute(
                    """
                    INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (opportunity_id, unit_id) DO UPDATE SET is_primary = EXCLUDED.is_primary
                    """,
                    opportunity_id, uid, is_prim
                )

        # Get units details for recommendation message
        presented_rows = await conn.fetch(
            """
            SELECT u.unit_id, u.unit_number, COALESCE(p.name_ar, p.name_en) AS project_name,
                   COALESCE(u.asking_price, u.rent_price, 0) as price
            FROM opportunity_units ou
            JOIN units u ON ou.unit_id = u.unit_id
            LEFT JOIN buildings b ON u.building_id = b.building_id
            LEFT JOIN projects p ON b.project_id = p.project_id
            WHERE ou.opportunity_id = $1
            LIMIT 5
            """,
            opportunity_id
        )

        units_summary = []
        for r in presented_rows:
            units_summary.append(f"وحدة #{r['unit_number']} ({r['project_name'] or 'المشروع'}) بسعر {float(r['price']):,.0f} ريال")
        units_text = " • " + "\n • ".join(units_summary) if units_summary else "مجموعة من الوحدات العقارية المختارة"

        # 2. Complete open matching tasks (standard or rental)
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE (opportunity_id = $2 OR ($3::text IS NOT NULL AND lead_id = $3))
              AND template_id IN ('TASK_OPPORTUNITY_MATCH_PROPERTIES', 'TASK_RENT_MATCH_PROPERTIES')
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            """,
            now_dt, opportunity_id, lead_id
        )

        # 3. Record Activity (ACT_RENT_PROPERTIES_MATCHED or ACT_OPPORTUNITY_PROPERTIES_PRESENTED)
        act_template = "ACT_RENT_PROPERTIES_MATCHED" if is_rent else "ACT_OPPORTUNITY_PROPERTIES_PRESENTED"
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id=act_template,
            user_id=agent_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            task_id=parent_task_id,
            outcome="PRESENTED",
            notes=notes or f"تم ترشيح وعرض الوحدات التالية على العميل:\n{units_text}",
            completed_at=now_dt
        )

        # 4. Record WhatsApp Communication COMM_OPPORTUNITY_RECOMMENDATIONS
        comm_id = await get_next_id(conn, "communications", "comm")
        comm_body = f"مرحباً بك، يسعدنا ترشيح هذه الوحدات العقارية المطابقة لمتطلباتك:\n{units_text}\nيسعدنا تحديد موعد للمعاينة الميدانية في الوقت الذي يناسبك."
        await conn.execute(
            """
            INSERT INTO communications (
                communication_id, customer_id, lead_id, channel, direction,
                subject, body, sent_at, delivery_status, template_id, created_at
            ) VALUES ($1, $2, $3, 'WHATSAPP', 'OUT', $4, $5, NOW(), 'SENT', 'COMM_OPPORTUNITY_RECOMMENDATIONS', NOW())
            """,
            comm_id, customer_id, lead_id,
            "توصيات عقارية مقترحة لطلبك العقاري",
            comm_body
        )

        # 5. Auto-spawn Viewing Schedule Task via Dynamic Transitions
        curr_matching_tmpl = "TASK_RENT_MATCH_PROPERTIES" if is_rent else "TASK_OPPORTUNITY_MATCH_PROPERTIES"
        db_next_tmpl = await WorkflowEngine.resolve_next_task_template(conn, curr_matching_tmpl, outcome="MATCHED")
        view_tmpl = db_next_tmpl or "TASK_VIEWING_SCHEDULE"
        viewing_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id=view_tmpl,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            customer_id=customer_id,
            assigned_user_id=agent_id,
            priority="HIGH",
            parent_task_id=parent_task_id
        )

        return {
            "status": "PROPERTIES_PRESENTED",
            "opportunity_id": opportunity_id,
            "lead_id": lead_id,
            "activity": activity,
            "recommendation_comm_id": comm_id,
            "viewing_task": viewing_task
        }

    @staticmethod
    async def schedule_property_viewing(
        conn: asyncpg.Connection,
        user_id: str,
        unit_id: str,
        scheduled_start: datetime,
        scheduled_end: Optional[datetime] = None,
        task_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        agent_user_id: Optional[str] = None,
        notes: Optional[str] = None,
        location_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage 3 Property Viewing Scheduling:
        Executes atomic business transitions:
          1. Resolves opportunity_id, customer_id, and agent_user_id from lead or task if needed.
          2. Inserts formal record into 'viewings' table with status 'SCHEDULED'.
          3. Completes TASK_VIEWING_SCHEDULE task.
          4. Advances Opportunity stage to 'VIEWING' and links unit in opportunity_units.
          5. Records immutable ACT_VIEWING_SCHEDULED activity (type VIEWING).
          6. Records COMM_VIEWING_CONFIRMATION outbound communication.
          7. Auto-spawns post-viewing inspection task TASK_VIEWING_REPORT with 2h SLA after visit.
        """
        now_dt = datetime.now(timezone.utc)

        if task_id:
            t_row = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
            if t_row:
                lead_id = lead_id or t_row["lead_id"]
                opportunity_id = opportunity_id or t_row["opportunity_id"]
                customer_id = customer_id or t_row["customer_id"]
                agent_user_id = agent_user_id or t_row["assigned_user_id"]

        # Ensure opportunity_id
        if not opportunity_id and lead_id:
            opp_row = await conn.fetchrow(
                "SELECT opportunity_id, customer_id, assigned_user_id FROM opportunities WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 1",
                lead_id
            )
            if opp_row:
                opportunity_id = opp_row["opportunity_id"]
                customer_id = customer_id or opp_row["customer_id"]
                agent_user_id = agent_user_id or opp_row["assigned_user_id"]
            else:
                if not customer_id:
                    customer_id = await conn.fetchval("SELECT customer_id FROM leads WHERE lead_id = $1", lead_id)
                new_opp_id = await get_next_id(conn, "opportunities", "opp")
                await conn.execute(
                    """
                    INSERT INTO opportunities (
                        opportunity_id, lead_id, customer_id, assigned_user_id, stage,
                        expected_value, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 0, NOW(), NOW())
                    """,
                    new_opp_id, lead_id, customer_id, agent_user_id or user_id
                )
                opportunity_id = new_opp_id

        if not customer_id:
            if lead_id:
                customer_id = await conn.fetchval("SELECT customer_id FROM leads WHERE lead_id = $1", lead_id)
            elif opportunity_id:
                customer_id = await conn.fetchval("SELECT customer_id FROM opportunities WHERE opportunity_id = $1", opportunity_id)

        if not agent_user_id:
            agent_user_id = user_id

        if not scheduled_end:
            scheduled_end = scheduled_start + timedelta(minutes=45)

        # Get unit details for rich message & activity
        u_info = await conn.fetchrow(
            """
            SELECT u.unit_number, COALESCE(p.name_ar, p.name_en) as project_name, b.name as building_name
            FROM units u
            LEFT JOIN buildings b ON u.building_id = b.building_id
            LEFT JOIN projects p ON b.project_id = p.project_id
            WHERE u.unit_id = $1
            """,
            unit_id
        )
        unit_number = u_info["unit_number"] if u_info else unit_id
        proj_name = u_info["project_name"] if (u_info and u_info["project_name"]) else "المشروع"

        viewing_id = await get_next_id(conn, "viewings", "viewing")
        all_notes = f"{notes or ''} {location_notes or ''}".strip() or None

        await conn.execute(
            """
            INSERT INTO viewings (
                viewing_id, opportunity_id, unit_id, customer_id, agent_user_id,
                scheduled_start, scheduled_end, status, notes, lead_id, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'SCHEDULED', $8, $9, NOW(), NOW())
            """,
            viewing_id, opportunity_id, unit_id, customer_id, agent_user_id,
            scheduled_start, scheduled_end, all_notes, lead_id
        )

        # 3. Complete any open TASK_VIEWING_SCHEDULE, TASK_VIEWING_RESCHEDULE, or TASK_INVEST_SCHEDULE_INSPECTION
        if task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, task_id
            )
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE template_id IN ('TASK_VIEWING_SCHEDULE', 'TASK_VIEWING_RESCHEDULE', 'TASK_INVEST_SCHEDULE_INSPECTION')
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
              AND (
                  ($2::text IS NOT NULL AND lead_id = $2) OR
                  ($3::text IS NOT NULL AND opportunity_id = $3)
              )
            """,
            now_dt, lead_id, opportunity_id
        )

        # 4. Advance Opportunity Stage to 'VIEWING' and link unit in opportunity_units
        if opportunity_id:
            await conn.execute(
                "UPDATE opportunities SET stage = 'VIEWING', updated_at = NOW() WHERE opportunity_id = $1",
                opportunity_id
            )
            await conn.execute(
                """
                INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary)
                VALUES ($1, $2, TRUE)
                ON CONFLICT (opportunity_id, unit_id) DO UPDATE SET is_primary = TRUE
                """,
                opportunity_id, unit_id
            )

        # 5. Check if Investment or Rental
        is_rent = False
        is_invest = False
        if lead_id:
            inq = await conn.fetchval("SELECT inquiry_type FROM leads WHERE lead_id = $1", lead_id)
            inq_u = (inq or "").upper()
            is_rent = (inq_u == "RENT")
            is_invest = (inq_u in ("INVEST", "INVESTMENT"))
        elif opportunity_id:
            inq = await conn.fetchval(
                "SELECT l.inquiry_type FROM opportunities o JOIN leads l ON o.lead_id = l.lead_id WHERE o.opportunity_id = $1",
                opportunity_id
            )
            inq_u = (inq or "").upper()
            is_rent = (inq_u == "RENT")
            is_invest = (inq_u in ("INVEST", "INVESTMENT"))

        # 6. Record Activity ACT_VIEWING_SCHEDULED or ACT_INVEST_INSPECTION_SCHEDULED
        start_str = scheduled_start.strftime("%Y-%m-%d %H:%M")
        sched_act_tmpl = "ACT_INVEST_INSPECTION_SCHEDULED" if is_invest else "ACT_VIEWING_SCHEDULED"
        inspect_label = "المعاينة والفحص الفني والاستثماري" if is_invest else "المعاينة الميدانية"
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id=sched_act_tmpl,
            user_id=agent_user_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            task_id=task_id,
            outcome="SCHEDULED",
            notes=f"تم تحديد موعد {inspect_label} للوحدة #{unit_number} بتاريخ {start_str}. {all_notes or ''}".strip(),
            completed_at=now_dt
        )

        # 7. Record Outbound Communication COMM_VIEWING_CONFIRMATION or COMM_INVEST_INSPECTION_CONFIRMATION
        comm_id = await get_next_id(conn, "communications", "comm")
        comm_tmpl = "COMM_INVEST_INSPECTION_CONFIRMATION" if is_invest else "COMM_VIEWING_CONFIRMATION"
        comm_subj = f"تأكيد موعد {inspect_label} للوحدة #{unit_number}"
        comm_msg = f"مرحباً بك، نود تأكيد موعد {inspect_label} للوحدة #{unit_number} بمشروع ({proj_name}). الموعد: {start_str}. {location_notes or ''}".strip()
        await conn.execute(
            """
            INSERT INTO communications (
                communication_id, customer_id, lead_id, channel, direction,
                subject, body, sent_at, delivery_status, template_id, created_at
            ) VALUES ($1, $2, $3, 'WHATSAPP', 'OUT', $4, $5, NOW(), 'SENT', $6, NOW())
            """,
            comm_id, customer_id, lead_id,
            comm_subj,
            comm_msg,
            comm_tmpl
        )

        # 8. Auto-spawn Post-Viewing Follow-up / Report Task via Dynamic Transitions
        report_due = scheduled_end + timedelta(hours=2)
        curr_sched_tmpl = "TASK_INVEST_SCHEDULE_INSPECTION" if is_invest else "TASK_VIEWING_SCHEDULE"
        db_next_tmpl = await WorkflowEngine.resolve_next_task_template(conn, curr_sched_tmpl, outcome="SCHEDULED")
        followup_tmpl = db_next_tmpl or ("TASK_INVEST_INSPECTION_REPORT" if is_invest else ("TASK_RENT_VIEWING_FOLLOW_UP" if is_rent else "TASK_VIEWING_REPORT"))

        report_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id=followup_tmpl,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            customer_id=customer_id,
            assigned_user_id=agent_user_id,
            custom_due_at=report_due,
            priority="HIGH",
            parent_task_id=task_id
        )

        return {
            "viewing_id": viewing_id,
            "status": "SCHEDULED",
            "opportunity_id": opportunity_id,
            "lead_id": lead_id,
            "unit_id": unit_id,
            "unit_number": unit_number,
            "scheduled_start": scheduled_start.isoformat(),
            "scheduled_end": scheduled_end.isoformat(),
            "activity": activity,
            "report_task": report_task,
            "new_stage": "VIEWING"
        }

    @staticmethod
    async def complete_property_viewing_report(
        conn: asyncpg.Connection,
        task_id: str,
        user_id: str,
        outcome: str,
        feedback_notes: Optional[str] = None,
        offer_amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Stage 3 Post-Viewing Inspection Report Completion:
        Executes atomic business transitions:
          1. Completes TASK_VIEWING_REPORT task.
          2. Finds associated viewing record and updates status & outcome.
          3. Records ACT_VIEWING_REPORT_SUBMITTED activity.
          4. If INTERESTED:
               - Advances Opportunity stage to 'NEGOTIATION'.
               - Auto-spawns Stage 4 TASK_OFFER_SUBMIT (Offer — Submit Formal Offer) with 12h SLA.
             If NEEDS_ANOTHER_UNIT:
               - Retains Opportunity in 'VIEWING'.
               - Auto-spawns new TASK_VIEWING_SCHEDULE for an alternative unit.
             If NOT_INTERESTED / DISQUALIFIED:
               - Documents client rejection rationale.
        """
        now_dt = datetime.now(timezone.utc)
        task = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        lead_id = task["lead_id"]
        opportunity_id = task["opportunity_id"]
        customer_id = task["customer_id"]
        agent_user_id = task["assigned_user_id"] or user_id

        # 1. Update associated Viewing record
        viewing = await conn.fetchrow(
            """
            SELECT viewing_id, unit_id, opportunity_id, customer_id, status
            FROM viewings
            WHERE (opportunity_id = $1 OR ($2::text IS NOT NULL AND lead_id = $2))
              AND status = 'SCHEDULED'
            ORDER BY scheduled_start DESC
            LIMIT 1
            """,
            opportunity_id, lead_id
        )
        if not viewing:
            viewing = await conn.fetchrow(
                """
                SELECT viewing_id, unit_id, opportunity_id, customer_id, status
                FROM viewings
                WHERE (opportunity_id = $1 OR ($2::text IS NOT NULL AND lead_id = $2))
                ORDER BY scheduled_start DESC
                LIMIT 1
                """,
                opportunity_id, lead_id
            )

        is_rent = False
        if lead_id:
            inq = await conn.fetchval("SELECT inquiry_type FROM leads WHERE lead_id = $1", lead_id)
            is_rent = (inq or "").upper() == "RENT"
        elif opportunity_id:
            inq = await conn.fetchval(
                "SELECT l.inquiry_type FROM opportunities o JOIN leads l ON o.lead_id = l.lead_id WHERE o.opportunity_id = $1",
                opportunity_id
            )
            is_rent = (inq or "").upper() == "RENT"

        # Resolve targeted unit and unit asking/rent price
        target_unit_id = viewing["unit_id"] if viewing and viewing["unit_id"] else None
        if not target_unit_id and opportunity_id:
            target_unit_id = await conn.fetchval(
                "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                opportunity_id
            )
        if not target_unit_id and lead_id:
            target_unit_id = await conn.fetchval("SELECT unit_id FROM leads WHERE lead_id = $1", lead_id)

        unit_row = None
        unit_price = None
        if target_unit_id:
            unit_row = await conn.fetchrow(
                "SELECT unit_id, unit_number, asking_price, rent_price FROM units WHERE unit_id = $1",
                target_unit_id
            )
            if unit_row:
                if is_rent and unit_row["rent_price"] is not None:
                    unit_price = float(unit_row["rent_price"])
                elif not is_rent and unit_row["asking_price"] is not None:
                    unit_price = float(unit_row["asking_price"])
                elif unit_row["asking_price"] is not None:
                    unit_price = float(unit_row["asking_price"])
                elif unit_row["rent_price"] is not None:
                    unit_price = float(unit_row["rent_price"])

        # Validate that the proposed offer does not exceed the unit asking/rent price
        parsed_offer_amount = None
        if offer_amount is not None:
            try:
                parsed_offer_amount = float(offer_amount)
            except (ValueError, TypeError):
                parsed_offer_amount = None

        if parsed_offer_amount is not None and parsed_offer_amount > 0:
            if unit_price is not None and unit_price > 0 and parsed_offer_amount > unit_price:
                price_type_lbl = "الإيجار" if is_rent else "البيع"
                raise ValueError(
                    f"لا يمكن أن يتجاوز العرض المالي المقترح ({parsed_offer_amount:,.2f} ريال) سعر {price_type_lbl} المعلن للوحدة ({unit_price:,.2f} ريال)."
                )

        v_status = "COMPLETED"
        if outcome in ("CANCELLED", "NO_SHOW"):
            v_status = outcome

        if viewing:
            await conn.execute(
                """
                UPDATE viewings
                SET status = $1, outcome = $2, notes = COALESCE(notes || E'\n', '') || $3, updated_at = NOW()
                WHERE viewing_id = $4
                """,
                v_status, outcome, feedback_notes or outcome, viewing["viewing_id"]
            )

        # 2. Mark report task completed
        await conn.execute(
            "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
            now_dt, task_id
        )

        # 3. Record Activity ACT_VIEWING_REPORT_SUBMITTED
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_VIEWING_REPORT_SUBMITTED",
            user_id=agent_user_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            task_id=task_id,
            outcome=outcome,
            notes=feedback_notes or f"تم توثيق تقرير المعاينة بنتيجة: {outcome}",
            completed_at=now_dt
        )

        next_action = None
        new_stage = None

        # 4. State Transitions based on outcome
        if outcome == "INTERESTED":
            new_stage = "NEGOTIATION"
            if opportunity_id:
                # Update opportunity expected value to the approved offer amount, or cap at unit price
                if parsed_offer_amount is not None and parsed_offer_amount > 0:
                    new_exp_val = parsed_offer_amount
                elif unit_price is not None and unit_price > 0:
                    curr_exp = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", opportunity_id)
                    curr_exp_f = float(curr_exp) if curr_exp is not None else unit_price
                    new_exp_val = min(curr_exp_f, unit_price)
                else:
                    new_exp_val = None

                if new_exp_val is not None:
                    await conn.execute(
                        "UPDATE opportunities SET stage = 'NEGOTIATION', expected_value = $1, updated_at = NOW() WHERE opportunity_id = $2",
                        new_exp_val, opportunity_id
                    )
                else:
                    await conn.execute(
                        "UPDATE opportunities SET stage = 'NEGOTIATION', updated_at = NOW() WHERE opportunity_id = $1",
                        opportunity_id
                    )

                if target_unit_id:
                    offered_to_set = parsed_offer_amount if (parsed_offer_amount is not None and parsed_offer_amount > 0) else unit_price
                    if offered_to_set is not None:
                        await conn.execute(
                            """
                            INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                            VALUES ($1, $2, TRUE, $3)
                            ON CONFLICT (opportunity_id, unit_id) DO UPDATE 
                            SET offered_price = EXCLUDED.offered_price
                            """,
                            opportunity_id, target_unit_id, offered_to_set
                        )
            curr_view_tmpl = "TASK_RENT_VIEWING_FOLLOW_UP" if is_rent else "TASK_VIEWING_REPORT"
            db_next = await WorkflowEngine.resolve_next_task_template(conn, curr_view_tmpl, outcome="INTERESTED")
            next_tmpl = db_next or ("TASK_RENT_PREPARE_TENANCY" if is_rent else "TASK_OFFER_SUBMIT")

            if is_rent:
                # Rental Pipeline: Dynamic task resolution
                tenancy_task, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id=next_tmpl,
                    lead_id=lead_id,
                    opportunity_id=opportunity_id,
                    customer_id=customer_id,
                    assigned_user_id=agent_user_id,
                    priority="HIGH",
                    parent_task_id=task_id
                )
                next_action = {"type": "TENANCY_PREPARATION_SPAWNED", "task": tenancy_task}
            else:
                # Sales Pipeline: Dynamic task resolution
                offer_task, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id=next_tmpl,
                    lead_id=lead_id,
                    opportunity_id=opportunity_id,
                    customer_id=customer_id,
                    assigned_user_id=agent_user_id,
                    priority="HIGH",
                    parent_task_id=task_id
                )
                next_action = {"type": "OFFER_TASK_SPAWNED", "task": offer_task}

        elif outcome == "NEEDS_ANOTHER_UNIT" or (outcome == "NOT_INTERESTED" and is_rent):
            new_stage = "VIEWING"
            curr_view_tmpl = "TASK_RENT_VIEWING_FOLLOW_UP" if is_rent else "TASK_VIEWING_REPORT"
            db_next = await WorkflowEngine.resolve_next_task_template(conn, curr_view_tmpl, outcome="NEEDS_ANOTHER_UNIT")
            if is_rent:
                rematch_tmpl = db_next or "TASK_RENT_MATCH_PROPERTIES"
                match_task, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id=rematch_tmpl,
                    lead_id=lead_id,
                    opportunity_id=opportunity_id,
                    customer_id=customer_id,
                    assigned_user_id=agent_user_id,
                    priority="NORMAL",
                    parent_task_id=task_id
                )
                next_action = {"type": "RENT_MATCH_SPAWNED", "task": match_task}
            else:
                sched_tmpl = db_next or "TASK_VIEWING_SCHEDULE"
                sched_task, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id=sched_tmpl,
                    lead_id=lead_id,
                    opportunity_id=opportunity_id,
                    customer_id=customer_id,
                    assigned_user_id=agent_user_id,
                    priority="NORMAL",
                    parent_task_id=task_id
                )
                next_action = {"type": "VIEWING_TASK_SPAWNED", "task": sched_task}
        elif outcome in ("NO_SHOW", "CANCELLED"):
            new_stage = "VIEWING"
            curr_view_tmpl = "TASK_RENT_VIEWING_FOLLOW_UP" if is_rent else "TASK_VIEWING_REPORT"
            db_next = await WorkflowEngine.resolve_next_task_template(conn, curr_view_tmpl, outcome="NO_SHOW")
            resched_tmpl = db_next or "TASK_VIEWING_RESCHEDULE"
            resched_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=resched_tmpl,
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_user_id,
                priority="HIGH",
                parent_task_id=task_id
            )
            next_action = {"type": "RESCHEDULE_TASK_SPAWNED", "task": resched_task}

        elif outcome in ("NOT_INTERESTED", "DISQUALIFIED"):
            new_stage = "LOST_INTEREST"
            if feedback_notes and opportunity_id:
                await conn.execute(
                    "UPDATE opportunities SET updated_at = NOW() WHERE opportunity_id = $1",
                    opportunity_id
                )

        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "viewing_id": viewing["viewing_id"] if viewing else None,
            "outcome": outcome,
            "activity": activity,
            "new_stage": new_stage,
            "next_action": next_action
        }

    @staticmethod
    async def submit_commercial_offer(
        conn: asyncpg.Connection,
        opportunity_id: str,
        unit_id: str,
        offer_amount: float,
        valid_until: Optional[Any] = None,
        user_id: Optional[str] = None,
        notes: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage E: Offer, Negotiation & Approval
        ======================================
        Submits commercial proposal, evaluates discount threshold against unit asking price (5% rule),
        spawns TASK_OFFER_MANAGER_APPROVAL if discount > 5%, or TASK_OFFER_FOLLOWUP + proposal communication
        if within standard authority.
        """
        now_dt = datetime.now(timezone.utc)
        opp = await conn.fetchrow(
            """
            SELECT o.opportunity_id, o.customer_id, o.lead_id, o.assigned_user_id, o.stage,
                   c.first_name, c.last_name, c.company_name, c.mobile, c.email
            FROM opportunities o
            JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.opportunity_id = $1
            """,
            opportunity_id
        )
        if not opp:
            raise ValueError(f"Opportunity '{opportunity_id}' not found.")

        unit = await conn.fetchrow(
            "SELECT unit_id, unit_number, asking_price, rent_price, status, building_id FROM units WHERE unit_id = $1",
            unit_id
        )
        if not unit:
            raise ValueError(f"Unit '{unit_id}' not found.")

        asking = float(unit["asking_price"] or unit["rent_price"] or offer_amount or 0)
        if asking > 0 and offer_amount > asking:
            raise ValueError(
                f"لا يمكن أن يتجاوز العرض المالي ({offer_amount:,.2f} ريال) سعر الوحدة العقارية المطلوب ({asking:,.2f} ريال)."
            )

        discount_pct = 0.0
        if asking > 0 and offer_amount < asking:
            discount_pct = round(((asking - offer_amount) / asking) * 100.0, 2)

        requires_manager_approval = (discount_pct > 5.0)
        offer_status = "PENDING_APPROVAL" if requires_manager_approval else "SUBMITTED"

        if not valid_until:
            valid_until_dt = now_dt + timedelta(days=7)
        elif isinstance(valid_until, str):
            valid_until_dt = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
        elif isinstance(valid_until, datetime):
            valid_until_dt = valid_until
        else:
            valid_until_dt = now_dt + timedelta(days=7)

        offer_id = await get_next_id(conn, "offers", "offer")
        await conn.execute(
            """
            INSERT INTO offers (offer_id, opportunity_id, unit_id, offer_amount, submitted_at, valid_until, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            offer_id, opportunity_id, unit_id, offer_amount, now_dt, valid_until_dt, offer_status
        )

        agent_id = user_id or opp["assigned_user_id"]
        act_notes = notes or f"تم إعداد وتقديم عرض مالي للوحدة {unit['unit_number']} بمبلغ {offer_amount:,.2f} ريال (نسبة الخصم: {discount_pct}%)."
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_OFFER_CREATED",
            user_id=agent_id,
            customer_id=opp["customer_id"],
            lead_id=opp["lead_id"],
            opportunity_id=opportunity_id,
            task_id=parent_task_id,
            outcome=offer_status,
            notes=act_notes,
            completed_at=now_dt
        )

        mgr_task = None
        followup_task = None

        if requires_manager_approval:
            branch_mgr_id = None
            if opp["assigned_user_id"]:
                branch_mgr_id = await conn.fetchval(
                    "SELECT manager_user_id FROM users WHERE user_id = $1",
                    opp["assigned_user_id"]
                )
            if not branch_mgr_id:
                branch_mgr_id = await conn.fetchval(
                    """
                    SELECT u.user_id 
                    FROM users u
                    JOIN user_roles ur ON u.user_id = ur.user_id
                    JOIN roles r ON ur.role_id = r.role_id
                    WHERE r.role_code IN ('BRANCH_MANAGER', 'SALES_DIRECTOR', 'GENERAL_MANAGER')
                    LIMIT 1
                    """
                ) or opp["assigned_user_id"] or user_id

            db_mgr = await WorkflowEngine.resolve_next_task_template(conn, "TASK_OFFER_SUBMIT", outcome="REQUIRES_APPROVAL")
            mgr_tmpl = db_mgr or "TASK_OFFER_MANAGER_APPROVAL"
            mgr_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=mgr_tmpl,
                lead_id=opp["lead_id"],
                opportunity_id=opportunity_id,
                customer_id=opp["customer_id"],
                assigned_user_id=branch_mgr_id or agent_id,
                priority="URGENT",
                custom_due_at=now_dt + timedelta(hours=4),
                parent_task_id=parent_task_id
            )
        else:
            await conn.execute(
                "UPDATE opportunities SET stage = 'OFFER', expected_value = $1, updated_at = NOW() WHERE opportunity_id = $2",
                offer_amount, opportunity_id
            )
            comm_id = await get_next_id(conn, "communications", "comm")
            cust_name = f"{opp['first_name'] or ''} {opp['last_name'] or ''}".strip() or opp["company_name"] or "العميل"
            await conn.execute(
                """
                INSERT INTO communications (
                    communication_id, customer_id, lead_id,
                    template_id, channel, direction, subject, body, delivery_status, sent_at, created_at
                ) VALUES (
                    $1, $2, $3,
                    'COMM_OFFER_PROPOSAL_SENT', 'WHATSAPP', 'OUT',
                    'عرض السعر الرسمي للوحدة العقارية — ري كيرم',
                    $4, 'SENT', $5, $5
                )
                """,
                comm_id, opp["customer_id"], opp["lead_id"],
                f"عزيزي {cust_name}، نرفق لك عرض السعر الرسمي للوحدة رقم {unit['unit_number']} بمبلغ {offer_amount:,.2f} ريال سعودي، ساري حتى تاريخ {valid_until_dt.strftime('%Y-%m-%d')}.",
                now_dt
            )
            followup_due = valid_until_dt - timedelta(hours=24)
            if followup_due <= now_dt:
                followup_due = now_dt + timedelta(hours=12)

            db_fup = await WorkflowEngine.resolve_next_task_template(conn, "TASK_OFFER_SUBMIT", outcome="SUBMITTED")
            followup_tmpl = db_fup or "TASK_OFFER_FOLLOWUP"
            followup_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=followup_tmpl,
                lead_id=opp["lead_id"],
                opportunity_id=opportunity_id,
                customer_id=opp["customer_id"],
                assigned_user_id=agent_id,
                priority="HIGH",
                custom_due_at=followup_due,
                parent_task_id=parent_task_id
            )

        if parent_task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, parent_task_id
            )

        return {
            "offer_id": offer_id,
            "opportunity_id": opportunity_id,
            "unit_id": unit_id,
            "offer_amount": offer_amount,
            "discount_pct": discount_pct,
            "status": offer_status,
            "valid_until": valid_until_dt.isoformat(),
            "activity": activity,
            "manager_approval_task": mgr_task,
            "followup_task": followup_task,
            "requires_manager_approval": requires_manager_approval
        }

    @staticmethod
    async def record_offer_decision(
        conn: asyncpg.Connection,
        offer_id: str,
        decision: str,
        counter_amount: Optional[float] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage E: Records negotiation decisions (ACCEPTED, REJECTED, COUNTERED, APPROVED).
        Automatically transitions stage and triggers appropriate next workflow tasks.
        """
        now_dt = datetime.now(timezone.utc)
        offer = await conn.fetchrow(
            """
            SELECT o.*, u.unit_number, u.asking_price, opp.customer_id, opp.lead_id, opp.assigned_user_id,
                   c.first_name, c.last_name, c.company_name
            FROM offers o
            JOIN units u ON o.unit_id = u.unit_id
            JOIN opportunities opp ON o.opportunity_id = opp.opportunity_id
            JOIN customers c ON opp.customer_id = c.customer_id
            WHERE o.offer_id = $1
            """,
            offer_id
        )
        if not offer:
            raise ValueError(f"Offer '{offer_id}' not found.")

        agent_id = user_id or offer["assigned_user_id"]
        norm_decision = decision.strip().upper()
        next_task = None
        new_opp_stage = None

        if norm_decision == "APPROVED":
            await conn.execute(
                "UPDATE offers SET status = 'SUBMITTED' WHERE offer_id = $1",
                offer_id
            )
            await conn.execute(
                "UPDATE opportunities SET stage = 'OFFER', expected_value = $1, updated_at = NOW() WHERE opportunity_id = $2",
                offer["offer_amount"], offer["opportunity_id"]
            )
            comm_id = await get_next_id(conn, "communications", "comm")
            cust_name = f"{offer['first_name'] or ''} {offer['last_name'] or ''}".strip() or offer["company_name"] or "العميل"
            await conn.execute(
                """
                INSERT INTO communications (
                    communication_id, customer_id, lead_id,
                    template_id, channel, direction, subject, body, delivery_status, sent_at, created_at
                ) VALUES (
                    $1, $2, $3,
                    'COMM_OFFER_PROPOSAL_SENT', 'WHATSAPP', 'OUT',
                    'عرض السعر الرسمي المعتمد للوحدة العقارية — ري كيرم',
                    $4, 'SENT', $5, $5
                )
                """,
                comm_id, offer["customer_id"], offer["lead_id"],
                f"عزيزي {cust_name}، نود إبلاغكم باعتماد عرض السعر للوحدة رقم {offer['unit_number']} بمبلغ {float(offer['offer_amount']):,.2f} ريال.",
                now_dt
            )
            followup_due = offer["valid_until"] - timedelta(hours=24) if offer["valid_until"] else now_dt + timedelta(days=2)
            if followup_due <= now_dt:
                followup_due = now_dt + timedelta(hours=12)

            db_apprv_next = await WorkflowEngine.resolve_next_task_template(conn, "TASK_OFFER_MANAGER_APPROVAL", outcome="APPROVED")
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=db_apprv_next or "TASK_OFFER_FOLLOWUP",
                lead_id=offer["lead_id"],
                opportunity_id=offer["opportunity_id"],
                customer_id=offer["customer_id"],
                assigned_user_id=agent_id,
                priority="HIGH",
                custom_due_at=followup_due,
                parent_task_id=parent_task_id
            )
            activity_notes = notes or f"تمت موافقة الإدارة على العرض المالي المخفض للوحدة {offer['unit_number']} وإرساله للعميل."

        elif norm_decision == "ACCEPTED":
            await conn.execute(
                "UPDATE offers SET status = 'ACCEPTED' WHERE offer_id = $1",
                offer_id
            )
            new_opp_stage = "NEGOTIATION"
            await conn.execute(
                "UPDATE opportunities SET stage = 'NEGOTIATION', expected_value = $1, updated_at = NOW() WHERE opportunity_id = $2",
                offer["offer_amount"], offer["opportunity_id"]
            )
            comm_id = await get_next_id(conn, "communications", "comm")
            cust_name = f"{offer['first_name'] or ''} {offer['last_name'] or ''}".strip() or offer["company_name"] or "العميل"
            await conn.execute(
                """
                INSERT INTO communications (
                    communication_id, customer_id, lead_id,
                    template_id, channel, direction, subject, body, delivery_status, sent_at, created_at
                ) VALUES (
                    $1, $2, $3,
                    'COMM_OFFER_DECISION_COMMUNICATED', 'WHATSAPP', 'OUT',
                    'تأكيد قبول العرض المالي والبدء بإجراءات الحجز — ري كيرم',
                    $4, 'SENT', $5, $5
                )
                """,
                comm_id, offer["customer_id"], offer["lead_id"],
                f"عزيزي {cust_name}، تم تأكيد قبول العرض المالي المقدم للوحدة رقم {offer['unit_number']}. جاري التنسيق لحجز الوحدة وسداد العربون.",
                now_dt
            )
            # Automatic Stage F Trigger: verify availability & reserve unit via dynamic transition
            db_acc_next = await WorkflowEngine.resolve_next_task_template(conn, "TASK_OFFER_FOLLOWUP", outcome="ACCEPTED")
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=db_acc_next or "TASK_RESERVATION_VERIFY_AVAILABILITY",
                lead_id=offer["lead_id"],
                opportunity_id=offer["opportunity_id"],
                customer_id=offer["customer_id"],
                assigned_user_id=agent_id,
                priority="URGENT",
                custom_due_at=now_dt + timedelta(hours=2),
                parent_task_id=parent_task_id
            )
            activity_notes = notes or f"تم قبول العرض المالي رسمياً بمبلغ {float(offer['offer_amount']):,.2f} ريال، وبدء إجراءات الحجز الفني."

        elif norm_decision == "COUNTERED":
            await conn.execute(
                "UPDATE offers SET status = 'COUNTERED' WHERE offer_id = $1",
                offer_id
            )
            c_amt_text = f"{counter_amount:,.2f} ريال" if counter_amount else "معدل"
            activity_notes = notes or f"تم تقديم عرض مالي مقابل من قبل العميل بمبلغ {c_amt_text}."
            db_cntr_next = await WorkflowEngine.resolve_next_task_template(conn, "TASK_OFFER_FOLLOWUP", outcome="COUNTER_OFFER")
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=db_cntr_next or "TASK_OFFER_PREPARE",
                lead_id=offer["lead_id"],
                opportunity_id=offer["opportunity_id"],
                customer_id=offer["customer_id"],
                assigned_user_id=agent_id,
                priority="HIGH",
                custom_due_at=now_dt + timedelta(hours=12),
                parent_task_id=parent_task_id
            )

        elif norm_decision == "REJECTED":
            await conn.execute(
                "UPDATE offers SET status = 'REJECTED' WHERE offer_id = $1",
                offer_id
            )
            activity_notes = notes or f"تم رفض العرض المالي للوحدة {offer['unit_number']}."
            lead_inq = await conn.fetchval("SELECT inquiry_type FROM leads WHERE lead_id = $1", offer["lead_id"]) if offer["lead_id"] else None
            inq_norm = (lead_inq or "").upper()
            if inq_norm == "RENT":
                rematch_tmpl = "TASK_RENT_MATCH_PROPERTIES"
            elif inq_norm in ("INVEST", "INVESTMENT"):
                rematch_tmpl = "TASK_INVEST_COMPARE_RETURNS"
            else:
                rematch_tmpl = "TASK_OPPORTUNITY_MATCH_PROPERTIES"

            db_rej_next = await WorkflowEngine.resolve_next_task_template(conn, "TASK_OFFER_FOLLOWUP", outcome="REJECTED")
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=db_rej_next or rematch_tmpl,
                lead_id=offer["lead_id"],
                opportunity_id=offer["opportunity_id"],
                customer_id=offer["customer_id"],
                assigned_user_id=agent_id,
                priority="NORMAL",
                custom_due_at=now_dt + timedelta(hours=24),
                parent_task_id=parent_task_id
            )
        else:
            raise ValueError(f"Unknown decision '{decision}'. Expected APPROVED, ACCEPTED, COUNTERED, or REJECTED.")

        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_OFFER_DECISION",
            user_id=agent_id,
            customer_id=offer["customer_id"],
            lead_id=offer["lead_id"],
            opportunity_id=offer["opportunity_id"],
            task_id=parent_task_id,
            outcome=norm_decision,
            notes=activity_notes,
            completed_at=now_dt
        )

        if parent_task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, parent_task_id
            )

        return {
            "offer_id": offer_id,
            "decision": norm_decision,
            "activity": activity,
            "next_task": next_task,
            "new_stage": new_opp_stage
        }

    @staticmethod
    async def execute_tenancy_agreement(
        conn: asyncpg.Connection,
        unit_id: str,
        tenant_customer_id: str,
        start_date: Any,
        end_date: Optional[Any] = None,
        rent_amount: float = 0.0,
        payment_frequency: str = "ANNUAL",
        deposit_amount: float = 0.0,
        contract_number: Optional[str] = None,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        generate_installments: bool = True,
        installments_count: int = 1,
        parent_task_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Rental Pipeline Execution Gateway:
        =================================
        Atomically executes tenancy contract and enforces business transitions:
        1. Checks unit status with FOR UPDATE row-level lock.
        2. Raises ValueError if unit is already RENTED or SOLD.
        3. Verifies customer exists.
        4. Generates tenancy_id and contract_number.
        5. Inserts into tenancies table with status 'ACTIVE'.
        6. Atomically updates units.status = 'RENTED'.
        7. Inserts into unit_status_history with audit reason.
        8. Generates rent collection installments if requested.
        9. Completes open TASK_RENT_PREPARE_TENANCY tasks.
        10. Spawns recurring TASK_RENT_COLLECTION_MONITORING task (72h SLA).
        11. Records immutable audit activity ACT_TENANCY_ACTIVATED.
        12. Advances opportunity stage to 'WON' and lead status to 'WON'.
        """
        now_dt = datetime.now(timezone.utc)
        effective_user_id = user_id or "user-51"

        # Normalize start_date and end_date to date objects
        if isinstance(start_date, datetime):
            s_date = start_date.date()
        elif isinstance(start_date, str):
            s_date = date.fromisoformat(start_date[:10])
        elif isinstance(start_date, date):
            s_date = start_date
        else:
            s_date = date.today()

        if isinstance(end_date, datetime):
            e_date = end_date.date()
        elif isinstance(end_date, str):
            e_date = date.fromisoformat(end_date[:10])
        elif isinstance(end_date, date):
            e_date = end_date
        else:
            e_date = s_date + timedelta(days=365)

        # 1. Lock unit with FOR UPDATE
        unit = await conn.fetchrow(
            "SELECT unit_id, unit_number, status, rent_price, asking_price FROM units WHERE unit_id = $1 FOR UPDATE",
            unit_id
        )
        if not unit:
            raise ValueError(f"Unit '{unit_id}' not found.")
        if unit["status"] in ("RENTED", "SOLD"):
            raise ValueError(f"الوحدة {unit['unit_number']} غير متاحة للإيجار حالياً (الحالة الحالية: {unit['status']}).")

        # Gating: verify that all statutory Saudi fees are collected before activating tenancy!
        if opportunity_id or lead_id:
            await WorkflowEngine.verify_saudi_fees_collected(
                conn=conn,
                opportunity_id=opportunity_id,
                lead_id=lead_id
            )

        # 2. Verify Customer
        cust = await conn.fetchrow(
            "SELECT customer_id, first_name, last_name, company_name, mobile FROM customers WHERE customer_id = $1",
            tenant_customer_id
        )
        if not cust:
            raise ValueError(f"Customer '{tenant_customer_id}' not found.")
        tenant_name = (f"{cust['first_name'] or ''} {cust['last_name'] or ''}").strip() or cust["company_name"]

        # 3. Contract number & ID
        if not contract_number:
            rnd = random.randint(1000, 9999)
            contract_number = f"TEN-{s_date.strftime('%Y%m')}-{rnd}"

        tenancy_id = await get_next_id(conn, "tenancies", "tenancy")
        final_rent = float(rent_amount) if rent_amount and float(rent_amount) > 0 else float(unit["rent_price"] or 30000.0)
        final_deposit = float(deposit_amount or 0.0)

        # 4. Insert Tenancy
        await conn.execute(
            """
            INSERT INTO tenancies (
                tenancy_id, unit_id, tenant_customer_id, contract_number,
                start_date, end_date, rent_amount, payment_frequency,
                deposit_amount, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'ACTIVE')
            """,
            tenancy_id, unit_id, tenant_customer_id, contract_number,
            s_date, e_date, final_rent, payment_frequency or "ANNUAL",
            final_deposit
        )

        # 5. Atomically update unit status to RENTED
        await conn.execute("UPDATE units SET status = 'RENTED', updated_at = NOW() WHERE unit_id = $1", unit_id)
        hist_id = await get_next_id(conn, "unit_status_history", "ush")
        await conn.execute(
            """
            INSERT INTO unit_status_history (
                unit_status_history_id, unit_id, old_status, new_status,
                changed_by_user_id, changed_at, reason
            ) VALUES ($1, $2, $3, 'RENTED', $4, NOW(), $5)
            """,
            hist_id, unit_id, unit["status"], effective_user_id, f"إبرام عقد إيجار {contract_number}"
        )

        # 6. Generate Rent Collection Installments
        installments = []
        if generate_installments and installments_count and installments_count > 0:
            count = min(12, max(1, installments_count))
            amount_per_installment = round(final_rent / count, 2)
            days_step = 30
            if count == 1:
                days_step = 0
            elif count == 2:
                days_step = 180
            elif count == 4:
                days_step = 90
            elif count == 12:
                days_step = 30
            else:
                days_step = max(1, int(365 / count))

            cur_due = s_date
            for i in range(count):
                due_d = cur_due + timedelta(days=i * days_step) if (i > 0 and days_step > 0) else cur_due
                rc_id = await get_next_id(conn, "rent_collections", "rent_collection")
                await conn.execute(
                    """
                    INSERT INTO rent_collections (
                        rent_collection_id, tenancy_id, due_date, amount_due, amount_paid, status
                    ) VALUES ($1, $2, $3, $4, 0, 'DUE')
                    """,
                    rc_id, tenancy_id, due_d, amount_per_installment
                )
                installments.append({
                    "rent_collection_id": rc_id,
                    "tenancy_id": tenancy_id,
                    "due_date": due_d.isoformat(),
                    "amount_due": amount_per_installment,
                    "amount_paid": 0.0,
                    "status": "DUE"
                })

        # 7. Complete open TASK_RENT_PREPARE_TENANCY tasks
        if parent_task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, parent_task_id
            )
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE template_id = 'TASK_RENT_PREPARE_TENANCY'
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
              AND (
                  ($2::text IS NOT NULL AND lead_id = $2) OR
                  ($3::text IS NOT NULL AND opportunity_id = $3) OR
                  customer_id = $4
              )
            """,
            now_dt, lead_id, opportunity_id, tenant_customer_id
        )

        # 8. Record Activity ACT_TENANCY_ACTIVATED
        act_notes = notes or f"تم إبرام وتفعيل عقد الإيجار {contract_number} للوحدة #{unit['unit_number']} بقيمة إيجارية {final_rent:,.2f} ريال."
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_TENANCY_ACTIVATED",
            user_id=effective_user_id,
            customer_id=tenant_customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            task_id=parent_task_id,
            outcome="ACTIVE",
            notes=act_notes,
            completed_at=now_dt
        )

        # 8.b Record internal Broker Commission for the leasing agent
        accountant_user_id = await conn.fetchval(
            """
            SELECT u.user_id FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.role_id
            WHERE r.role_code = 'ACCOUNTANT'
            ORDER BY u.created_at ASC
            LIMIT 1
            """
        ) or "user-19"

        comm_agent_id = effective_user_id or (await conn.fetchval("SELECT assigned_user_id FROM units WHERE unit_id = $1", unit_id))
        existing_comm = await conn.fetchrow(
            "SELECT commission_id FROM commissions WHERE contract_id = $1 OR contract_id = $2",
            tenancy_id, contract_number
        )
        if not existing_comm and comm_agent_id:
            linked_contract_id = await conn.fetchval(
                "SELECT contract_id FROM contracts WHERE contract_number = $1 LIMIT 1",
                contract_number
            )
            if not linked_contract_id:
                linked_contract_id = await get_next_id(conn, "contracts", "con")
                await conn.execute(
                    """
                    INSERT INTO contracts (
                        contract_id, reservation_id, contract_number, contract_type,
                        start_date, end_date, contract_value, signed_at, status
                    ) VALUES ($1, NULL, $2, 'RENT', $3, $4, $5, $6, 'ACTIVE')
                    """,
                    linked_contract_id, contract_number, s_date, e_date, final_rent, now_dt
                )

            agent_profile = await conn.fetchrow("""
                SELECT user_id, full_name, compensation_type, 
                       CAST(base_salary AS FLOAT) AS base_salary,
                       CAST(sales_commission_rate AS FLOAT) AS sales_commission_rate,
                       CAST(rent_commission_rate AS FLOAT) AS rent_commission_rate,
                       CAST(sales_fixed_cut AS FLOAT) AS sales_fixed_cut,
                       CAST(rent_fixed_cut AS FLOAT) AS rent_fixed_cut
                FROM users WHERE user_id = $1
            """, comm_agent_id)

            from app.services.calculation_service import CalculationService
            calc = CalculationService.calculate_agent_commission(
                transaction_type="RENT",
                deal_value=final_rent,
                agent_profile=dict(agent_profile) if agent_profile else None
            )

            comm_id = await get_next_id(conn, "commissions", "comm")
            await conn.execute(
                """
                INSERT INTO commissions (
                    commission_id, contract_id, user_id, commission_type, rate, amount, status,
                    compensation_type, gross_deal_value, gross_brokerage_amount,
                    gov_fees_deducted, net_commission_base, calculation_notes
                )
                VALUES ($1, $2, $3, 'RENT', $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                comm_id, linked_contract_id, comm_agent_id, calc["rate"], calc["amount"], calc["status"],
                calc["compensation_type"], calc["gross_deal_value"], calc["gross_brokerage_amount"],
                calc["gov_fees_deducted"], calc["net_commission_base"], calc["calculation_notes"]
            )

            # Spawn TASK_COMMISSION_SETTLEMENT for Finance/Accountant if not salaried and amount > 0
            if calc["amount"] > 0 and calc["status"] != "EXEMPT_SALARY":
                agent_name = await conn.fetchval("SELECT full_name FROM users WHERE user_id = $1", comm_agent_id) or "الوسيط"
                comm_task_title = f"المالية — تدقيق واعتماد وصرف عمولة الوسيط ({agent_name} — عقد {contract_number} — {calc['amount']:,.2f} ر.س)"
                await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id="TASK_COMMISSION_SETTLEMENT",
                    lead_id=lead_id,
                    opportunity_id=opportunity_id,
                    customer_id=tenant_customer_id,
                    assigned_user_id=accountant_user_id,
                    priority="NORMAL",
                    custom_title=comm_task_title,
                    parent_task_id=parent_task_id
                )

        # 9. Spawn Recurring Monitoring Task TASK_RENT_COLLECTION_MONITORING
        monitoring_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_RENT_COLLECTION_MONITORING",
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            customer_id=tenant_customer_id,
            assigned_user_id=effective_user_id,
            priority="NORMAL",
            parent_task_id=parent_task_id
        )

        # 10. Update Lead and Opportunity to WON
        if opportunity_id:
            await conn.execute(
                "UPDATE opportunities SET stage = 'WON', updated_at = NOW() WHERE opportunity_id = $1",
                opportunity_id
            )
        if lead_id:
            await conn.execute(
                "UPDATE leads SET status = 'WON', updated_at = NOW() WHERE lead_id = $1",
                lead_id
            )

        return {
            "tenancy_id": tenancy_id,
            "tenancy": {
                "tenancy_id": tenancy_id,
                "unit_id": unit_id,
                "tenant_customer_id": tenant_customer_id,
                "contract_number": contract_number,
                "start_date": s_date,
                "end_date": e_date,
                "rent_amount": final_rent,
                "payment_frequency": payment_frequency or "ANNUAL",
                "deposit_amount": final_deposit,
                "status": "ACTIVE"
            },
            "unit_number": unit["unit_number"],
            "tenant_name": tenant_name,
            "tenant_mobile": cust.get("mobile"),
            "installments": installments,
            "activity": activity,
            "monitoring_task": monitoring_task
        }

    @staticmethod
    async def create_unit_reservation(
        conn: asyncpg.Connection,
        opportunity_id: str,
        unit_id: str,
        customer_id: str,
        deposit_amount: Optional[float] = None,
        expiry_hours: int = 48,
        user_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage F: Reservation & Financial Coordination
        =============================================
        Performs strict transactional concurrency verification:
        1. Checks unit status with FOR UPDATE row-level lock.
        2. Raises ValueError if unit is not AVAILABLE (prevents race condition).
        3. Inserts into reservations table (ACTIVE).
        4. Atomically updates units.status = 'RESERVED'.
        5. Inserts into unit_status_history with audit reason.
        6. Advances opportunity stage to 'RESERVATION'.
        7. Spawns TASK_RESERVATION_DEPOSIT_FOLLOWUP for ACCOUNTANT (48h SLA).
        8. Records ACT_RESERVATION_CONFIRMED.
        9. Sends COMM_RESERVATION_CONFIRMATION to customer.
        """
        now_dt = datetime.now(timezone.utc)
        expires_at = now_dt + timedelta(hours=expiry_hours or 48)

        unit = await conn.fetchrow(
            "SELECT unit_id, unit_number, asking_price, rent_price, status, building_id FROM units WHERE unit_id = $1 FOR UPDATE",
            unit_id
        )
        if not unit:
            raise ValueError(f"Unit '{unit_id}' not found.")
        if unit["status"] != "AVAILABLE":
            raise ValueError(f"الوحدة {unit['unit_number']} غير متاحة للحجز حالياً (الحالة الحالية: {unit['status']}).")

        res_id = await get_next_id(conn, "reservations", "res")
        res_count = await conn.fetchval("SELECT count(*) + 1 FROM reservations")
        res_number = f"RES-{res_count:06d}"

        if deposit_amount is None:
            price = float(unit["asking_price"] or unit["rent_price"] or 500000.0)
            deposit_amount = round(price * 0.05, 2)

        await conn.execute(
            """
            INSERT INTO reservations (
                reservation_id, opportunity_id, unit_id, customer_id,
                reservation_number, reserved_at, expires_at, deposit_amount, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'ACTIVE')
            """,
            res_id, opportunity_id, unit_id, customer_id,
            res_number, now_dt, expires_at, deposit_amount
        )

        await conn.execute(
            "UPDATE units SET status = 'RESERVED', updated_at = NOW() WHERE unit_id = $1",
            unit_id
        )

        hist_id = await get_next_id(conn, "unit_status_history", "ush")
        await conn.execute(
            """
            INSERT INTO unit_status_history (
                unit_status_history_id, unit_id, old_status, new_status,
                changed_by_user_id, changed_at, reason
            ) VALUES ($1, $2, 'AVAILABLE', 'RESERVED', $3, $4, $5)
            """,
            hist_id, unit_id, user_id, now_dt, f"حجز الوحدة بموجب الحجز {res_number}"
        )

        opp = await conn.fetchrow("SELECT lead_id, assigned_user_id FROM opportunities WHERE opportunity_id = $1", opportunity_id)
        lead_id = opp["lead_id"] if opp else None
        agent_id = user_id or (opp["assigned_user_id"] if opp else None)

        await conn.execute(
            "UPDATE opportunities SET stage = 'RESERVATION', updated_at = NOW() WHERE opportunity_id = $1",
            opportunity_id
        )

        # Auto-supersede and complete any prior uncompleted tasks for this opportunity/lead
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE (opportunity_id = $2 OR (lead_id = $3 AND $3 IS NOT NULL))
              AND status IN ('OPEN', 'PENDING', 'IN_PROGRESS')
              AND template_id != 'TASK_RESERVATION_DEPOSIT_FOLLOWUP'
            """,
            now_dt, opportunity_id, lead_id
        )

        finance_user_id = await conn.fetchval(
            """
            SELECT u.user_id 
            FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.role_id
            WHERE r.role_code IN ('ACCOUNTANT', 'FINANCE')
            LIMIT 1
            """
        ) or agent_id

        db_dep = await WorkflowEngine.resolve_next_task_template(conn, "TASK_RESERVATION_VERIFY_AVAILABILITY", outcome="CONFIRMED")
        dep_tmpl = db_dep or "TASK_RESERVATION_DEPOSIT_FOLLOWUP"
        deposit_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id=dep_tmpl,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            customer_id=customer_id,
            assigned_user_id=finance_user_id,
            priority="HIGH",
            custom_due_at=expires_at,
            parent_task_id=parent_task_id
        )

        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_RESERVATION_CONFIRMED",
            user_id=agent_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            task_id=parent_task_id,
            outcome="CONFIRMED",
            notes=notes or f"تم حجز الوحدة {unit['unit_number']} بنجاح بموجب الحجز {res_number}. العربون المطلوب: {deposit_amount:,.2f} ريال.",
            completed_at=now_dt
        )

        comm_id = await get_next_id(conn, "communications", "comm")
        await conn.execute(
            """
            INSERT INTO communications (
                communication_id, customer_id, lead_id,
                template_id, channel, direction, subject, body, delivery_status, sent_at, created_at
            ) VALUES (
                $1, $2, $3,
                'COMM_RESERVATION_CONFIRMATION', 'WHATSAPP', 'OUT',
                'تأكيد حجز الوحدة العقارية وبيانات العربون — ري كيرم',
                $4, 'SENT', $5, $5
            )
            """,
            comm_id, customer_id, lead_id,
            f"تم تأكيد حجز الوحدة رقم {unit['unit_number']} برقم حجز {res_number}. يرجى سداد العربون وقدره {deposit_amount:,.2f} ريال قبل انتهاء المهلة في {expires_at.strftime('%Y-%m-%d %H:%M')}.",
            now_dt
        )

        if parent_task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, parent_task_id
            )

        return {
            "reservation_id": res_id,
            "reservation_number": res_number,
            "unit_id": unit_id,
            "deposit_amount": deposit_amount,
            "expires_at": expires_at.isoformat(),
            "status": "ACTIVE",
            "deposit_task": deposit_task,
            "activity": activity
        }

    @staticmethod
    async def verify_reservation_deposit(
        conn: asyncpg.Connection,
        reservation_id: str,
        amount_received: float,
        payment_method: str = "BANK_TRANSFER",
        payment_ref: Optional[str] = None,
        user_id: Optional[str] = None,
        notes: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage F: Confirms deposit received and verified by Finance.
        Advances reservation status to CONFIRMED.
        Automatically spawns Stage G task: TASK_CONTRACT_DRAFT for Legal.
        """
        now_dt = datetime.now(timezone.utc)
        res = await conn.fetchrow(
            """
            SELECT r.*, u.unit_number, o.lead_id, o.assigned_user_id
            FROM reservations r
            JOIN units u ON r.unit_id = u.unit_id
            LEFT JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE r.reservation_id = $1
            """,
            reservation_id
        )
        if not res:
            raise ValueError(f"Reservation '{reservation_id}' not found.")

        await conn.execute(
            "UPDATE reservations SET status = 'CONFIRMED' WHERE reservation_id = $1",
            reservation_id
        )

        agent_id = user_id or res["assigned_user_id"]
        v_notes = notes or f"تم التحقق من استلام العربون بمبلغ {amount_received:,.2f} ريال عبر {payment_method} (مرجع: {payment_ref or 'مؤكد'})."
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_RESERVATION_AVAILABILITY_VERIFIED",
            user_id=agent_id,
            customer_id=res["customer_id"],
            lead_id=res["lead_id"],
            opportunity_id=res["opportunity_id"],
            task_id=parent_task_id,
            outcome="DEPOSIT_VERIFIED",
            notes=v_notes,
            completed_at=now_dt
        )

        if parent_task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, parent_task_id
            )
        else:
            await conn.execute(
                """
                UPDATE tasks SET status = 'COMPLETED', completed_at = $1
                WHERE opportunity_id = $2 AND template_id = 'TASK_RESERVATION_DEPOSIT_FOLLOWUP' AND status IN ('PENDING', 'OPEN')
                """,
                now_dt, res["opportunity_id"]
            )

        legal_user_id = await conn.fetchval(
            """
            SELECT u.user_id 
            FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.role_id
            WHERE r.role_code IN ('LEGAL', 'CONTRACTS')
            LIMIT 1
            """
        ) or agent_id

        db_draft = await WorkflowEngine.resolve_next_task_template(conn, "TASK_RESERVATION_DEPOSIT_FOLLOWUP", outcome="DEPOSIT_VERIFIED")
        draft_tmpl = db_draft or "TASK_CONTRACT_DRAFT"
        draft_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id=draft_tmpl,
            lead_id=res["lead_id"],
            opportunity_id=res["opportunity_id"],
            customer_id=res["customer_id"],
            assigned_user_id=legal_user_id,
            priority="HIGH",
            parent_task_id=parent_task_id
        )

        return {
            "reservation_id": reservation_id,
            "status": "CONFIRMED",
            "deposit_verified": True,
            "activity": activity,
            "draft_task": draft_task
        }

    @staticmethod
    async def initiate_contract_draft(
        conn: asyncpg.Connection,
        reservation_id: str,
        contract_type: str = "SALE",
        contract_value: Optional[float] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        user_id: Optional[str] = None,
        notes: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage G: Contract Preparation, Signing and Closure
        =================================================
        Initiates official contract draft from reservation.
        Inserts contract record with status = 'DRAFT'.
        Records ACT_CONTRACT_DRAFT_CREATED.
        Spawns TASK_CONTRACT_INTERNAL_REVIEW for legal reviewer.
        Sends COMM_CONTRACT_REVIEW_REQUIRED internal notification.
        """
        now_dt = datetime.now(timezone.utc)
        res = await conn.fetchrow(
            """
            SELECT r.*, u.unit_number, u.asking_price, u.rent_price, o.lead_id, o.assigned_user_id, o.expected_value
            FROM reservations r
            JOIN units u ON r.unit_id = u.unit_id
            LEFT JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE r.reservation_id = $1
            """,
            reservation_id
        )
        if not res:
            raise ValueError(f"Reservation '{reservation_id}' not found.")

        if res["status"] == "CONVERTED":
            raise ValueError("تم تحويل هذا الحجز إلى عقد مسبقاً (Reservation already converted).")

        # Guard against duplicate contract drafts for the same reservation
        existing_contract = await conn.fetchrow(
            """
            SELECT contract_id, contract_number, status 
            FROM contracts 
            WHERE reservation_id = $1 AND status NOT IN ('CANCELLED', 'TERMINATED')
            ORDER BY contract_id DESC LIMIT 1
            """,
            reservation_id
        )
        if existing_contract:
            raise ValueError(
                f"يوجد عقد مسبق مرتبط بهذا الحجز برقم {existing_contract['contract_number']} بحالة ({existing_contract['status']}). لا يمكن إنشاء عقد مكرر لنفس الحجز والصفقة."
            )

        if not contract_value:
            offer_val = await conn.fetchval(
                "SELECT offer_amount FROM offers WHERE opportunity_id = $1 AND status = 'ACCEPTED' ORDER BY submitted_at DESC LIMIT 1",
                res["opportunity_id"]
            )
            if offer_val:
                contract_value = float(offer_val)
            elif res.get("expected_value"):
                contract_value = float(res["expected_value"])
            else:
                contract_value = float(res["asking_price"] or res["rent_price"] or 500000.0)
        val = contract_value
        c_count = await conn.fetchval("SELECT count(*) + 1 FROM contracts")
        c_number = f"CON-{c_count:06d}"
        contract_id = await get_next_id(conn, "contracts", "con")

        await conn.execute(
            """
            INSERT INTO contracts (
                contract_id, reservation_id, contract_number, contract_type,
                start_date, end_date, contract_value, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'DRAFT')
            """,
            contract_id, reservation_id, c_number, contract_type.upper(),
            start_date or date.today(), end_date, val
        )

        agent_id = user_id or res["assigned_user_id"]
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_CONTRACT_DRAFT_CREATED",
            user_id=agent_id,
            customer_id=res["customer_id"],
            lead_id=res["lead_id"],
            opportunity_id=res["opportunity_id"],
            task_id=parent_task_id,
            outcome="DRAFT_CREATED",
            notes=notes or f"تم إعداد مسودة العقد رقم {c_number} بقيمة {val:,.2f} ريال.",
            completed_at=now_dt
        )

        legal_user_id = await conn.fetchval(
            """
            SELECT u.user_id 
            FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.role_id
            WHERE r.role_code IN ('LEGAL', 'CONTRACTS')
            LIMIT 1
            """
        ) or agent_id

        db_review = await WorkflowEngine.resolve_next_task_template(conn, "TASK_CONTRACT_DRAFT", outcome="SUBMITTED")
        review_tmpl = db_review or "TASK_CONTRACT_INTERNAL_REVIEW"
        review_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id=review_tmpl,
            lead_id=res["lead_id"],
            opportunity_id=res["opportunity_id"],
            customer_id=res["customer_id"],
            assigned_user_id=legal_user_id,
            priority="HIGH",
            parent_task_id=parent_task_id
        )

        comm_id = await get_next_id(conn, "communications", "comm")
        await conn.execute(
            """
            INSERT INTO communications (
                communication_id, customer_id, lead_id,
                template_id, channel, direction, subject, body, delivery_status, sent_at, created_at
            ) VALUES (
                $1, $2, $3,
                'COMM_CONTRACT_REVIEW_REQUIRED', 'EMAIL', 'INTERNAL',
                'طلب مراجعة واعتماد مسودة عقد بيع/إيجار — ري كيرم',
                $4, 'SENT', $5, $5
            )
            """,
            comm_id, res["customer_id"], res["lead_id"],
            f"مسودة العقد رقم {c_number} للوحدة {res['unit_number']} جاهزة للمراجعة القانونية والاعتماد الداخلي.",
            now_dt
        )

        if parent_task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, parent_task_id
            )

        return {
            "contract_id": contract_id,
            "contract_number": c_number,
            "contract_value": val,
            "status": "DRAFT",
            "review_task": review_task,
            "activity": activity
        }

    @staticmethod
    async def advance_contract_lifecycle(
        conn: asyncpg.Connection,
        contract_id: str,
        action: str,
        payload: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage G: Contract Progression & Closure Engine
        =============================================
        Handles structured transitions:
        - APPROVE_DRAFT: Advances DRAFT -> PENDING_SIGNATURE, spawns TASK_CONTRACT_SIGNATURE, sends instructions.
        - RECORD_SIGNATURE: Advances PENDING_SIGNATURE -> SIGNED, sets signed_at, generates payment schedule (DUE),
                            spawns TASK_CONTRACT_RECONCILIATION & TASK_CONTRACT_HANDOVER.
        - COMPLETE_HANDOVER / DEAL_CLOSURE: Verifies handover & finance, advances to COMPLETED/ACTIVE,
                                           updates units.status = 'SOLD' (with unit_status_history),
                                           opportunities.stage = 'CLOSED_WON', records ACT_CONTRACT_CLOSED.
        """
        now_dt = datetime.now(timezone.utc)
        payload = payload or {}

        c = await conn.fetchrow(
            """
            SELECT c.*, r.unit_id, r.customer_id, r.opportunity_id, r.deposit_amount,
                   u.unit_number, u.asking_price, o.lead_id, o.assigned_user_id,
                   cust.first_name, cust.last_name, cust.company_name
            FROM contracts c
            LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
            LEFT JOIN units u ON r.unit_id = u.unit_id
            LEFT JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            LEFT JOIN customers cust ON r.customer_id = cust.customer_id
            WHERE c.contract_id = $1
            """,
            contract_id
        )
        if not c:
            raise ValueError(f"Contract '{contract_id}' not found.")

        agent_id = user_id or c["assigned_user_id"]
        norm_action = action.strip().upper()
        next_task = None
        activity = None

        if norm_action == "APPROVE_DRAFT":
            await conn.execute(
                "UPDATE contracts SET status = 'PENDING_SIGNATURE' WHERE contract_id = $1",
                contract_id
            )
            db_sig = await WorkflowEngine.resolve_next_task_template(conn, "TASK_CONTRACT_INTERNAL_REVIEW", outcome="APPROVED")
            sig_tmpl = db_sig or "TASK_CONTRACT_SIGNATURE"
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=sig_tmpl,
                lead_id=c["lead_id"],
                opportunity_id=c["opportunity_id"],
                customer_id=c["customer_id"],
                assigned_user_id=agent_id,
                priority="HIGH",
                custom_due_at=now_dt + timedelta(hours=48),
                parent_task_id=parent_task_id
            )
            comm_id = await get_next_id(conn, "communications", "comm")
            cust_name = f"{c['first_name'] or ''} {c['last_name'] or ''}".strip() or c["company_name"] or "العميل"
            await conn.execute(
                """
                INSERT INTO communications (
                    communication_id, customer_id, lead_id,
                    template_id, channel, direction, subject, body, delivery_status, sent_at, created_at
                ) VALUES (
                    $1, $2, $3,
                    'COMM_CONTRACT_SIGNATURE_INSTRUCTIONS', 'WHATSAPP', 'OUT',
                    'رابط وإرشادات توقيع العقد النهائي — ري كيرم',
                    $4, 'SENT', $5, $5
                )
                """,
                comm_id, c["customer_id"], c["lead_id"],
                f"عزيزي {cust_name}، نود إشعاركم بأن العقد رقم {c['contract_number']} للوحدة {c['unit_number']} جاهز للتوقيع. يرجى مراجعة وتوقيع النسخة المعتمدة.",
                now_dt
            )
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_CONTRACT_DRAFT_CREATED",
                user_id=agent_id,
                customer_id=c["customer_id"],
                lead_id=c["lead_id"],
                opportunity_id=c["opportunity_id"],
                task_id=parent_task_id,
                outcome="APPROVED_FOR_SIGNATURE",
                notes=f"تمت المراجعة القانونية للعقد رقم {c['contract_number']} وإرساله لتوقيع العميل.",
                completed_at=now_dt
            )

        elif norm_action == "RECORD_SIGNATURE":
            await conn.execute(
                "UPDATE contracts SET status = 'SIGNED', signed_at = $1 WHERE contract_id = $2",
                now_dt, contract_id
            )
            if c["reservation_id"]:
                await conn.execute(
                    "UPDATE reservations SET status = 'CONVERTED' WHERE reservation_id = $1",
                    c["reservation_id"]
                )

            deposit = float(c["deposit_amount"] or 0)
            contract_val = float(c["contract_value"] or 0)

            if deposit > 0:
                pay_id1 = await get_next_id(conn, "payments", "pay")
                p_count1 = await conn.fetchval("SELECT count(*) + 1 FROM payments")
                await conn.execute(
                    """
                    INSERT INTO payments (payment_id, contract_id, payment_reference, due_date, amount_due, amount_paid, paid_at, method, status)
                    VALUES ($1, $2, $3, CURRENT_DATE, $4, $4, $5, 'BANK_TRANSFER', 'PAID')
                    """,
                    pay_id1, contract_id, f"PAY-{p_count1:06d}", deposit, now_dt
                )
                remaining = max(0.0, contract_val - deposit)
                if remaining > 0:
                    pay_id2 = await get_next_id(conn, "payments", "pay")
                    p_count2 = await conn.fetchval("SELECT count(*) + 1 FROM payments")
                    await conn.execute(
                        """
                        INSERT INTO payments (payment_id, contract_id, payment_reference, due_date, amount_due, amount_paid, status)
                        VALUES ($1, $2, $3, CURRENT_DATE + 30, $4, 0, 'DUE')
                        """,
                        pay_id2, contract_id, f"PAY-{p_count2:06d}", remaining
                    )
            else:
                pay_id1 = await get_next_id(conn, "payments", "pay")
                p_count1 = await conn.fetchval("SELECT count(*) + 1 FROM payments")
                await conn.execute(
                    """
                    INSERT INTO payments (payment_id, contract_id, payment_reference, due_date, amount_due, amount_paid, status)
                    VALUES ($1, $2, $3, CURRENT_DATE + 14, $4, 0, 'DUE')
                    """,
                    pay_id1, contract_id, f"PAY-{p_count1:06d}", contract_val
                )

            comm_agent_id = c["assigned_user_id"] or user_id or await conn.fetchval("SELECT user_id FROM users LIMIT 1")
            agent_profile = await conn.fetchrow("""
                SELECT user_id, full_name, compensation_type, 
                       CAST(base_salary AS FLOAT) AS base_salary,
                       CAST(sales_commission_rate AS FLOAT) AS sales_commission_rate,
                       CAST(rent_commission_rate AS FLOAT) AS rent_commission_rate,
                       CAST(sales_fixed_cut AS FLOAT) AS sales_fixed_cut,
                       CAST(rent_fixed_cut AS FLOAT) AS rent_fixed_cut
                FROM users WHERE user_id = $1
            """, comm_agent_id)

            from app.services.calculation_service import CalculationService
            calc = CalculationService.calculate_agent_commission(
                transaction_type="SALE",
                deal_value=contract_val,
                agent_profile=dict(agent_profile) if agent_profile else None
            )

            comm_id = await get_next_id(conn, "commissions", "comm")
            await conn.execute(
                """
                INSERT INTO commissions (
                    commission_id, contract_id, user_id, commission_type, rate, amount, status,
                    compensation_type, gross_deal_value, gross_brokerage_amount,
                    gov_fees_deducted, net_commission_base, calculation_notes
                )
                VALUES ($1, $2, $3, 'SALES', $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                comm_id, contract_id, comm_agent_id, calc["rate"], calc["amount"], calc["status"],
                calc["compensation_type"], calc["gross_deal_value"], calc["gross_brokerage_amount"],
                calc["gov_fees_deducted"], calc["net_commission_base"], calc["calculation_notes"]
            )

            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_CONTRACT_SIGNED",
                user_id=agent_id,
                customer_id=c["customer_id"],
                lead_id=c["lead_id"],
                opportunity_id=c["opportunity_id"],
                task_id=parent_task_id,
                outcome="SIGNED",
                notes=f"تم توثيق توقيع العقد رقم {c['contract_number']} رسمياً وجدولة الدفعات.",
                completed_at=now_dt
            )

            finance_user_id = await conn.fetchval(
                """
                SELECT u.user_id 
                FROM users u
                JOIN user_roles ur ON u.user_id = ur.user_id
                JOIN roles r ON ur.role_id = r.role_id
                WHERE r.role_code IN ('ACCOUNTANT', 'FINANCE')
                LIMIT 1
                """
            ) or agent_id

            await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_CONTRACT_RECONCILIATION",
                lead_id=c["lead_id"],
                opportunity_id=c["opportunity_id"],
                customer_id=c["customer_id"],
                assigned_user_id=finance_user_id,
                priority="HIGH",
                custom_due_at=now_dt + timedelta(hours=48),
                parent_task_id=parent_task_id
            )

            if calc["amount"] > 0 and calc["status"] != "EXEMPT_SALARY":
                comm_agent_name = await conn.fetchval("SELECT full_name FROM users WHERE user_id = $1", comm_agent_id) or "الوسيط"
                comm_task_title = f"المالية — تدقيق واعتماد وصرف عمولة الوسيط ({comm_agent_name} — عقد {c['contract_number']} — {calc['amount']:,.2f} ر.س)"
                await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id="TASK_COMMISSION_SETTLEMENT",
                    lead_id=c["lead_id"],
                    opportunity_id=c["opportunity_id"],
                    customer_id=c["customer_id"],
                    assigned_user_id=finance_user_id,
                    priority="NORMAL",
                    custom_due_at=now_dt + timedelta(hours=72),
                    custom_title=comm_task_title,
                    parent_task_id=parent_task_id
                )

            pm_user_id = await conn.fetchval(
                """
                SELECT u.user_id 
                FROM users u
                JOIN user_roles ur ON u.user_id = ur.user_id
                JOIN roles r ON ur.role_id = r.role_id
                WHERE r.role_code IN ('PROPERTY_MANAGEMENT', 'OPERATIONS', 'SALES_AGENT')
                LIMIT 1
                """
            ) or agent_id

            db_handover = await WorkflowEngine.resolve_next_task_template(conn, "TASK_CONTRACT_SIGNATURE", outcome="SIGNED")
            handover_tmpl = db_handover or "TASK_CONTRACT_HANDOVER"
            if handover_tmpl:
                next_task, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id=handover_tmpl,
                    lead_id=c["lead_id"],
                    opportunity_id=c["opportunity_id"],
                    customer_id=c["customer_id"],
                    assigned_user_id=pm_user_id,
                    priority="NORMAL",
                    custom_due_at=now_dt + timedelta(hours=72),
                    parent_task_id=parent_task_id
                )

        elif norm_action in ("COMPLETE_HANDOVER", "CLOSE_CONTRACT"):
            # Gating: verify that all statutory Saudi fees (brokerage + VAT, RETT / Ejar fees) are paid!
            await WorkflowEngine.verify_saudi_fees_collected(
                conn=conn,
                opportunity_id=c["opportunity_id"],
                lead_id=c["lead_id"],
                contract_id=contract_id
            )
            await conn.execute(
                "UPDATE contracts SET status = 'ACTIVE' WHERE contract_id = $1",
                contract_id
            )
            if c["unit_id"]:
                new_unit_status = "SOLD" if c["contract_type"] == "SALE" else "RENTED"
                await conn.execute(
                    "UPDATE units SET status = $1, updated_at = NOW() WHERE unit_id = $2",
                    new_unit_status, c["unit_id"]
                )
                hist_id = await get_next_id(conn, "unit_status_history", "ush")
                await conn.execute(
                    """
                    INSERT INTO unit_status_history (
                        unit_status_history_id, unit_id, old_status, new_status,
                        changed_by_user_id, changed_at, reason
                    ) VALUES ($1, $2, 'RESERVED', $3, $4, $5, $6)
                    """,
                    hist_id, c["unit_id"], new_unit_status, user_id, now_dt,
                    f"اكتمال تسليم العقار بموجب العقد {c['contract_number']}"
                )

            if c["opportunity_id"]:
                await conn.execute(
                    "UPDATE opportunities SET stage = 'CLOSED_WON', updated_at = NOW() WHERE opportunity_id = $1",
                    c["opportunity_id"]
                )

            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_CONTRACT_CLOSED",
                user_id=agent_id,
                customer_id=c["customer_id"],
                lead_id=c["lead_id"],
                opportunity_id=c["opportunity_id"],
                task_id=parent_task_id,
                outcome="CLOSED_WON",
                notes=f"تم إغلاق الصفقة بنجاح وتسليم الوحدة {c['unit_number']} للمشتري بموجب العقد {c['contract_number']}.",
                completed_at=now_dt
            )
        elif norm_action in ("CANCEL", "CANCEL_CONTRACT", "VOID"):
            # 1. Update contract status to CANCELLED
            await conn.execute(
                "UPDATE contracts SET status = 'CANCELLED' WHERE contract_id = $1",
                contract_id
            )

            # 2. Automatically void / cancel unpaid payments linked to this contract
            await conn.execute(
                "UPDATE payments SET status = 'CANCELLED' WHERE contract_id = $1 AND status != 'PAID'",
                contract_id
            )

            # 3. Automatically void / cancel pending or approved commissions linked to this contract
            await conn.execute(
                "UPDATE commissions SET status = 'CANCELLED' WHERE contract_id = $1 AND status != 'PAID'",
                contract_id
            )

            # 4. Cancel any open operational tasks associated with this contract / opportunity
            if c["opportunity_id"]:
                await conn.execute(
                    """
                    UPDATE tasks 
                    SET status = 'CANCELLED', completed_at = $1 
                    WHERE opportunity_id = $2 
                      AND template_id IN ('TASK_CONTRACT_INTERNAL_REVIEW', 'TASK_CONTRACT_SIGNATURE', 'TASK_CONTRACT_RECONCILIATION', 'TASK_CONTRACT_HANDOVER')
                      AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
                    """,
                    now_dt, c["opportunity_id"]
                )

            # 5. Check if unit status should be released back to AVAILABLE or RESERVED
            if c["unit_id"]:
                active_res = await conn.fetchrow(
                    """
                    SELECT reservation_id FROM reservations 
                    WHERE unit_id = $1 AND status = 'ACTIVE' AND reservation_id != COALESCE($2, '')
                    LIMIT 1
                    """,
                    c["unit_id"], c["reservation_id"]
                )
                new_unit_status = "RESERVED" if active_res else "AVAILABLE"
                curr_status = await conn.fetchval("SELECT status FROM units WHERE unit_id = $1", c["unit_id"])
                if curr_status != new_unit_status:
                    await conn.execute(
                        "UPDATE units SET status = $1, updated_at = NOW() WHERE unit_id = $2",
                        new_unit_status, c["unit_id"]
                    )
                    hist_id = await get_next_id(conn, "unit_status_history", "ush")
                    await conn.execute(
                        """
                        INSERT INTO unit_status_history (
                            unit_status_history_id, unit_id, old_status, new_status,
                            changed_by_user_id, changed_at, reason
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        hist_id, c["unit_id"], curr_status, new_unit_status, user_id, now_dt,
                        f"إلغاء العقد رقم {c['contract_number']} وتحديث حالة الوحدة إلى {new_unit_status}"
                    )

            cancel_notes = payload.get("notes") or f"تم إلغاء العقد رقم {c['contract_number']} وإلغاء كافة الدفعات والعمولات والمهام التشغيلية المعلقة المرتبطة به."
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_CONTRACT_CLOSED",
                user_id=agent_id,
                customer_id=c["customer_id"],
                lead_id=c["lead_id"],
                opportunity_id=c["opportunity_id"],
                task_id=parent_task_id,
                outcome="CANCELLED",
                notes=cancel_notes,
                completed_at=now_dt
            )
        else:
            raise ValueError(f"Unknown contract action '{action}'. Expected APPROVE_DRAFT, RECORD_SIGNATURE, COMPLETE_HANDOVER, or CANCEL.")

        if parent_task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, parent_task_id
            )

        return {
            "contract_id": contract_id,
            "action": norm_action,
            "activity": activity,
            "next_task": next_task
        }

    @staticmethod
    async def generate_saudi_fee_invoices(
        conn: asyncpg.Connection,
        opportunity_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        contract_id: Optional[str] = None,
        transaction_type: Optional[str] = None,
        deal_value: Optional[float] = None,
        rett_exempt: bool = False,
        rett_notes: Optional[str] = None,
        security_deposit: float = 0.0,
        buyer_brokerage_percent: float = 2.5,
        seller_brokerage_percent: float = 0.0,
        user_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Saudi Statutory Real Estate Invoicing Engine
        ===========================================
        Generates compliant, separated tax invoices for both Customer (Buyer/Tenant) and Owner (Seller/Lessor):
        1. Customer (المشتري / المستأجر):
           - Brokerage Commission (السعي): 2.5% (or specified %)
           - VAT on Brokerage: 15%
           - Optional Refundable Security Deposit (if rental)
        2. Owner (البائع / المؤجر):
           - Sale: Real Estate Transaction Tax (ضريبة التصرفات العقارية - RETT 5% ZATCA)
           - Rent: Ejar National Platform Network Documentation Fee (125 SAR residential / 200 SAR commercial)
        3. Auditing & Tasking:
           - Records separate ACT_INVOICE_GENERATED events in activities.
           - Spawns TASK_COLLECT_SAUDI_FEES assigned to ACCOUNTANT.
        """
        now_dt = datetime.now(timezone.utc)
        opp_row = None
        lead_row = None
        customer_id = None
        agent_id = user_id

        if opportunity_id:
            opp_row = await conn.fetchrow(
                """
                SELECT o.*, c.first_name, c.last_name, c.company_name, c.mobile,
                       l.inquiry_type, l.unit_id as lead_unit_id
                FROM opportunities o
                LEFT JOIN customers c ON o.customer_id = c.customer_id
                LEFT JOIN leads l ON o.lead_id = l.lead_id
                WHERE o.opportunity_id = $1
                """,
                opportunity_id
            )
            if opp_row:
                customer_id = opp_row["customer_id"]
                if not lead_id and opp_row["lead_id"]:
                    lead_id = opp_row["lead_id"]
                agent_id = agent_id or opp_row["assigned_user_id"]

        if lead_id and not customer_id:
            lead_row = await conn.fetchrow(
                """
                SELECT l.*, c.first_name, c.last_name, c.company_name, c.mobile
                FROM leads l
                LEFT JOIN customers c ON l.customer_id = c.customer_id
                WHERE l.lead_id = $1
                """,
                lead_id
            )
            if lead_row:
                customer_id = lead_row["customer_id"]
                agent_id = agent_id or lead_row["assigned_user_id"]

        if not customer_id:
            raise ValueError("Customer ID could not be identified from opportunity or lead.")

        # Resolve Unit ID if not provided
        if not unit_id:
            if opportunity_id:
                unit_id = await conn.fetchval(
                    """
                    SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1
                    UNION
                    SELECT unit_id FROM reservations WHERE opportunity_id = $1 AND status != 'CANCELLED'
                    UNION
                    SELECT r.unit_id FROM contracts c JOIN reservations r ON c.reservation_id = r.reservation_id WHERE r.opportunity_id = $1
                    LIMIT 1
                    """,
                    opportunity_id
                )
            if not unit_id and lead_id:
                unit_id = await conn.fetchval(
                    """
                    SELECT unit_id FROM leads WHERE lead_id = $1 AND unit_id IS NOT NULL
                    UNION
                    SELECT unit_id FROM lead_units WHERE lead_id = $1
                    LIMIT 1
                    """,
                    lead_id
                )

        unit_row = None
        owner_customer_id = None
        unit_number = "--"
        is_commercial = False
        if unit_id:
            unit_row = await conn.fetchrow(
                """
                SELECT u.unit_id, u.unit_number, u.asking_price, u.rent_price, u.owner_customer_id,
                       pt.category as property_category,
                       c.first_name, c.last_name, c.company_name, c.mobile
                FROM units u
                LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
                LEFT JOIN customers c ON u.owner_customer_id = c.customer_id
                WHERE u.unit_id = $1
                """,
                unit_id
            )
            if unit_row:
                unit_number = unit_row["unit_number"]
                owner_customer_id = unit_row["owner_customer_id"]
                is_commercial = (unit_row["property_category"] or "").upper() == "COMMERCIAL"

        if not owner_customer_id:
            owner_customer_id = await conn.fetchval(
                "SELECT customer_id FROM customers WHERE customer_type IN ('OWNER', 'LESSOR') LIMIT 1"
            ) or customer_id

        # Determine transaction type
        if not transaction_type:
            if contract_id:
                c_type = await conn.fetchval("SELECT contract_type FROM contracts WHERE contract_id = $1", contract_id)
                if c_type:
                    transaction_type = c_type.upper()
            if not transaction_type and opp_row:
                inq = (opp_row["inquiry_type"] or "").upper()
                transaction_type = "RENT" if inq == "RENT" else "SALE"
            elif not transaction_type and lead_row:
                inq = (lead_row["inquiry_type"] or "").upper()
                transaction_type = "RENT" if inq == "RENT" else "SALE"
            else:
                transaction_type = transaction_type or "SALE"
        transaction_type = transaction_type.upper()

        # Determine deal value
        if not deal_value or float(deal_value) <= 0:
            if contract_id:
                c_val = await conn.fetchval("SELECT contract_value FROM contracts WHERE contract_id = $1", contract_id)
                if c_val and float(c_val) > 0:
                    deal_value = float(c_val)
            if (not deal_value or float(deal_value) <= 0) and opp_row and opp_row.get("expected_value"):
                deal_value = float(opp_row["expected_value"])
            if (not deal_value or float(deal_value) <= 0) and unit_row:
                val = unit_row["rent_price"] if transaction_type == "RENT" else unit_row["asking_price"]
                if val and float(val) > 0:
                    deal_value = float(val)
        deal_value = float(deal_value or 100000.0)

        # Idempotency check: if invoices already exist for this opportunity/lead, return them
        existing_invoices = await conn.fetch(
            """
            SELECT inv.*,
                   COALESCE(c.first_name || ' ' || c.last_name, c.company_name) as payer_customer_name,
                   c.mobile as payer_customer_mobile,
                   u.unit_number
            FROM invoices inv
            LEFT JOIN customers c ON inv.payer_customer_id = c.customer_id
            LEFT JOIN units u ON inv.unit_id = u.unit_id
            WHERE (
                ($1::text IS NOT NULL AND inv.opportunity_id = $1) OR
                ($2::text IS NOT NULL AND inv.lead_id = $2)
            ) AND inv.status != 'CANCELLED'
            ORDER BY inv.created_at ASC
            """,
            opportunity_id, lead_id
        )
        if existing_invoices and len(existing_invoices) >= 2:
            inv_list = []
            for row in existing_invoices:
                r_dict = dict(row)
                r_dict["subtotal"] = float(r_dict.get("subtotal") or 0)
                r_dict["vat_rate"] = float(r_dict.get("vat_rate") or 0)
                r_dict["vat_amount"] = float(r_dict.get("vat_amount") or 0)
                r_dict["total_amount"] = float(r_dict.get("total_amount") or 0)
                r_dict["amount_paid"] = float(r_dict.get("amount_paid") or 0)
                r_dict["line_items"] = r_dict["line_items"] if isinstance(r_dict["line_items"], list) else json.loads(r_dict["line_items"] or "[]")
                inv_list.append(r_dict)
            return {
                "message": "Fee invoices already exist for this deal.",
                "already_existed": True,
                "invoices": inv_list
            }

        # Helper for unique invoice number
        async def gen_inv_number(suffix: str) -> str:
            for _ in range(50):
                rnd = random.randint(1000, 9999)
                candidate = f"INV-{now_dt.strftime('%Y%m')}-{rnd:04d}-{suffix}"
                exists = await conn.fetchval("SELECT 1 FROM invoices WHERE invoice_number = $1", candidate)
                if not exists:
                    return candidate
            return f"INV-{now_dt.strftime('%Y%m%d%H%M%S')}-{suffix}"

        created_invoices = []

        # 1. Generate Customer Invoice (Brokerage 2.5% + 15% VAT)
        cust_inv_id = await get_next_id(conn, "invoices", "inv")
        cust_inv_num = await gen_inv_number("CUST")
        brokerage_pct = float(buyer_brokerage_percent or 2.5)
        brokerage_amount = round(deal_value * (brokerage_pct / 100.0), 2)
        cust_vat = round(brokerage_amount * 0.15, 2)
        deposit_val = float(security_deposit or 0.0)

        cust_line_items = [
            {
                "item_ar": f"عمولة وساطة عقارية نظامية ({brokerage_pct}%)",
                "item_en": f"Statutory Brokerage Commission ({brokerage_pct}%)",
                "amount": brokerage_amount,
                "vat_rate": 15.0,
                "vat_amount": cust_vat,
                "total": round(brokerage_amount + cust_vat, 2)
            }
        ]
        if deposit_val > 0 and transaction_type == "RENT":
            cust_line_items.append({
                "item_ar": "مبلغ التأمين المسترد للوحدة الإيجارية",
                "item_en": "Refundable Security Deposit",
                "amount": deposit_val,
                "vat_rate": 0.0,
                "vat_amount": 0.0,
                "total": deposit_val
            })

        cust_subtotal = round(brokerage_amount + (deposit_val if transaction_type == "RENT" else 0.0), 2)
        cust_total = round(cust_subtotal + cust_vat, 2)

        await conn.execute(
            """
            INSERT INTO invoices (
                invoice_id, invoice_number, invoice_type, payer_type, payer_customer_id,
                opportunity_id, lead_id, contract_id, unit_id, transaction_type,
                subtotal, vat_rate, vat_amount, total_amount, amount_paid, status,
                line_items, due_date, notes, created_at, updated_at
            ) VALUES (
                $1, $2, 'TAX_INVOICE', 'CUSTOMER', $3,
                $4, $5, $6, $7, $8,
                $9, 15.00, $10, $11, 0.0, 'PENDING',
                $12::jsonb, CURRENT_DATE + 7, $13, $14, $14
            )
            """,
            cust_inv_id, cust_inv_num, customer_id,
            opportunity_id, lead_id, contract_id, unit_id, transaction_type,
            cust_subtotal, cust_vat, cust_total,
            json.dumps(cust_line_items),
            notes or f"فاتورة عمولة الوساطة العقارية للعميل — وحدة {unit_number}",
            now_dt
        )

        cust_activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_INVOICE_GENERATED",
            user_id=agent_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            outcome="INVOICE_ISSUED",
            notes=f"تم إصدار الفاتورة الضريبية رقم {cust_inv_num} للعميل بمبلغ {cust_total:,.2f} ريال (السعي والضريبة).",
            completed_at=now_dt
        )

        created_invoices.append({
            "invoice_id": cust_inv_id,
            "invoice_number": cust_inv_num,
            "payer_type": "CUSTOMER",
            "payer_customer_id": customer_id,
            "total_amount": cust_total,
            "subtotal": cust_subtotal,
            "vat_amount": cust_vat,
            "status": "PENDING"
        })

        # 2. Generate Owner Invoice (RETT 5% on Sale or Ejar platform fee on Rent)
        owner_inv_id = await get_next_id(conn, "invoices", "inv")
        owner_inv_num = await gen_inv_number("OWNR")
        owner_line_items = []
        owner_subtotal = 0.0
        owner_vat = 0.0
        owner_fee_desc = ""

        if transaction_type == "RENT":
            ejar_fee = 200.0 if is_commercial else 125.0
            owner_fee_desc = f"رسوم شبكة إيجار الوطنية ({'تجاري 200 ريال' if is_commercial else 'سكني 125 ريال'})"
            owner_line_items.append({
                "item_ar": f"رسوم توثيق العقد عبر شبكة إيجار الوطنية ({'تجاري' if is_commercial else 'سكني'})",
                "item_en": f"Ejar Platform Contract Documentation Fee ({'Commercial' if is_commercial else 'Residential'})",
                "amount": ejar_fee,
                "vat_rate": 0.0,
                "vat_amount": 0.0,
                "total": ejar_fee
            })
            owner_subtotal = ejar_fee
            owner_vat = 0.0
        else: # SALE
            rett_pct = 5.0
            rett_amount = 0.0 if rett_exempt else round(deal_value * (rett_pct / 100.0), 2)
            owner_fee_desc = f"ضريبة التصرفات العقارية (5% هيئة الزكاة والضريبة والجمارك): {rett_amount:,.2f} ريال"
            if rett_exempt:
                owner_fee_desc = f"إعفاء ضريبة التصرفات العقارية — {rett_notes or 'إعفاء مسكن أول أو مستثنى'}"
            owner_line_items.append({
                "item_ar": "ضريبة التصرفات العقارية (5% — هيئة الزكاة والضريبة والجمارك)" if not rett_exempt else "ضريبة التصرفات العقارية (معفى نظامياً)",
                "item_en": "Real Estate Transaction Tax (RETT 5% — ZATCA)" if not rett_exempt else "RETT (Statutorily Exempt)",
                "amount": rett_amount,
                "vat_rate": 0.0,
                "vat_amount": 0.0,
                "total": rett_amount
            })
            owner_subtotal = rett_amount
            owner_vat = 0.0

            if seller_brokerage_percent and float(seller_brokerage_percent) > 0:
                s_rate = float(seller_brokerage_percent)
                s_brokerage = round(deal_value * (s_rate / 100.0), 2)
                s_vat = round(s_brokerage * 0.15, 2)
                owner_line_items.append({
                    "item_ar": f"سعي ووساطة عقارية مستحقة على المالك ({s_rate}%)",
                    "item_en": f"Seller Brokerage Commission ({s_rate}%)",
                    "amount": s_brokerage,
                    "vat_rate": 15.0,
                    "vat_amount": s_vat,
                    "total": round(s_brokerage + s_vat, 2)
                })
                owner_subtotal = round(owner_subtotal + s_brokerage, 2)
                owner_vat = round(owner_vat + s_vat, 2)

        owner_total = round(owner_subtotal + owner_vat, 2)

        await conn.execute(
            """
            INSERT INTO invoices (
                invoice_id, invoice_number, invoice_type, payer_type, payer_customer_id,
                opportunity_id, lead_id, contract_id, unit_id, transaction_type,
                subtotal, vat_rate, vat_amount, total_amount, amount_paid, status,
                line_items, due_date, notes, created_at, updated_at
            ) VALUES (
                $1, $2, 'TAX_INVOICE', 'OWNER', $3,
                $4, $5, $6, $7, $8,
                $9, $10, $11, $12, 0.0, 'PENDING',
                $13::jsonb, CURRENT_DATE + 7, $14, $15, $15
            )
            """,
            owner_inv_id, owner_inv_num, owner_customer_id,
            opportunity_id, lead_id, contract_id, unit_id, transaction_type,
            owner_subtotal, (15.0 if owner_vat > 0 else 0.0), owner_vat, owner_total,
            json.dumps(owner_line_items),
            notes or f"فاتورة الرسوم النظامية للمالك — وحدة {unit_number} ({owner_fee_desc})",
            now_dt
        )

        owner_activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_INVOICE_GENERATED",
            user_id=agent_id,
            customer_id=owner_customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            outcome="INVOICE_ISSUED",
            notes=f"تم إصدار فاتورة الرسوم النظامية رقم {owner_inv_num} للمالك بمبلغ {owner_total:,.2f} ريال ({owner_fee_desc}).",
            completed_at=now_dt
        )

        created_invoices.append({
            "invoice_id": owner_inv_id,
            "invoice_number": owner_inv_num,
            "payer_type": "OWNER",
            "payer_customer_id": owner_customer_id,
            "total_amount": owner_total,
            "subtotal": owner_subtotal,
            "vat_amount": owner_vat,
            "status": "PENDING"
        })

        # 3. Spawn TASK_COLLECT_SAUDI_FEES assigned to Accountant
        accountant_user_id = await conn.fetchval(
            """
            SELECT u.user_id FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.role_id
            WHERE r.role_code = 'ACCOUNTANT'
            ORDER BY u.created_at ASC
            LIMIT 1
            """
        ) or "user-19"

        # Resolve contract number if exists
        contract_num = None
        if contract_id:
            contract_num = await conn.fetchval("SELECT contract_number FROM contracts WHERE contract_id = $1", contract_id)
        if not contract_num and opportunity_id:
            contract_num = await conn.fetchval(
                """
                SELECT c.contract_number FROM contracts c
                JOIN reservations r ON c.reservation_id = r.reservation_id
                WHERE r.opportunity_id = $1
                UNION
                SELECT contract_number FROM tenancies WHERE tenant_customer_id = (SELECT customer_id FROM opportunities WHERE opportunity_id = $1)
                LIMIT 1
                """,
                opportunity_id
            )
        if not contract_num and lead_id:
            contract_num = await conn.fetchval(
                """
                SELECT contract_number FROM tenancies WHERE tenant_customer_id = (SELECT customer_id FROM leads WHERE lead_id = $1)
                LIMIT 1
                """,
                lead_id
            )

        ref_label = f"لعقد {contract_num}" if contract_num else (f"للوحدة #{unit_number}" if unit_number and unit_number != "--" else "للصفقة")
        fee_task_title = f"المالية — تحصيل سعي الوساطة ({cust_subtotal:,.2f} ر.س + ضريبة) والرسوم {ref_label}"

        task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_COLLECT_SAUDI_FEES",
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            customer_id=customer_id,
            assigned_user_id=accountant_user_id,
            priority="HIGH",
            custom_due_at=now_dt + timedelta(hours=48),
            custom_title=fee_task_title
        )

        return {
            "message": "Statutory Saudi fee invoices generated successfully.",
            "already_existed": False,
            "invoices": created_invoices,
            "task": task
        }

    @staticmethod
    async def collect_fee_invoice(
        conn: asyncpg.Connection,
        invoice_id: str,
        payment_method: str = "BANK_TRANSFER",
        payment_reference: Optional[str] = None,
        amount: Optional[float] = None,
        user_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Registers payment collection for a statutory Saudi fee invoice.
        Audits transaction in activities and automatically completes TASK_COLLECT_SAUDI_FEES
        when all fee invoices for the deal are settled.
        """
        now_dt = datetime.now(timezone.utc)
        inv = await conn.fetchrow(
            """
            SELECT inv.*,
                   COALESCE(c.first_name || ' ' || c.last_name, c.company_name) as payer_name
            FROM invoices inv
            LEFT JOIN customers c ON inv.payer_customer_id = c.customer_id
            WHERE inv.invoice_id = $1
            """,
            invoice_id
        )
        if not inv:
            raise ValueError(f"Invoice '{invoice_id}' not found.")

        if inv["status"] == "PAID":
            return {"invoice_id": invoice_id, "status": "PAID", "message": "Invoice already paid."}

        paid_val = float(amount) if amount and float(amount) > 0 else float(inv["total_amount"])
        p_ref = payment_reference or f"TRX-{now_dt.strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

        await conn.execute(
            """
            UPDATE invoices
            SET status = 'PAID',
                amount_paid = $1,
                paid_at = $2,
                payment_method = $3,
                payment_reference = $4,
                notes = COALESCE($5, notes),
                updated_at = $2
            WHERE invoice_id = $6
            """,
            paid_val, now_dt, payment_method, p_ref, notes, invoice_id
        )

        payer_type_ar = "العميل" if inv["payer_type"] == "CUSTOMER" else "المالك"
        payer_name = inv.get("payer_name") or payer_type_ar

        # Record ACT_FEE_COLLECTED Activity
        act = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_FEE_COLLECTED",
            user_id=user_id or inv["payer_customer_id"],
            customer_id=inv["payer_customer_id"],
            lead_id=inv["lead_id"],
            opportunity_id=inv["opportunity_id"],
            outcome="COLLECTED",
            notes=f"تم تأكيد تحصيل وتوريد فاتورة {payer_type_ar} ({payer_name}) رقم {inv['invoice_number']} بمبلغ {paid_val:,.2f} ريال عبر {payment_method} (مرجع التحويل: {p_ref}).",
            completed_at=now_dt
        )

        # Check if all fee invoices for this deal are now PAID
        opp_id = inv["opportunity_id"]
        lead_id = inv["lead_id"]
        unpaid_count = await conn.fetchval(
            """
            SELECT count(*) FROM invoices
            WHERE (
                ($1::text IS NOT NULL AND opportunity_id = $1) OR
                ($2::text IS NOT NULL AND lead_id = $2)
            ) AND status != 'PAID' AND status != 'CANCELLED'
            """,
            opp_id, lead_id
        )

        all_collected = (unpaid_count == 0)
        if all_collected:
            await conn.execute(
                """
                UPDATE tasks
                SET status = 'COMPLETED', completed_at = $1
                WHERE template_id = 'TASK_COLLECT_SAUDI_FEES'
                  AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
                  AND (
                      ($2::text IS NOT NULL AND opportunity_id = $2) OR
                      ($3::text IS NOT NULL AND lead_id = $3)
                  )
                """,
                now_dt, opp_id, lead_id
            )

        updated_row = await conn.fetchrow(
            """
            SELECT inv.*,
                   COALESCE(c.first_name || ' ' || c.last_name, c.company_name) as payer_customer_name,
                   c.mobile as payer_customer_mobile,
                   u.unit_number
            FROM invoices inv
            LEFT JOIN customers c ON inv.payer_customer_id = c.customer_id
            LEFT JOIN units u ON inv.unit_id = u.unit_id
            WHERE inv.invoice_id = $1
            """,
            invoice_id
        )
        res = dict(updated_row)
        res["all_fees_collected"] = all_collected
        res["subtotal"] = float(res.get("subtotal") or 0)
        res["vat_rate"] = float(res.get("vat_rate") or 0)
        res["vat_amount"] = float(res.get("vat_amount") or 0)
        res["total_amount"] = float(res.get("total_amount") or 0)
        res["amount_paid"] = float(res.get("amount_paid") or 0)
        res["line_items"] = res["line_items"] if isinstance(res["line_items"], list) else json.loads(res["line_items"] or "[]")
        return res

    @staticmethod
    async def verify_saudi_fees_collected(
        conn: asyncpg.Connection,
        opportunity_id: Optional[str] = None,
        lead_id: Optional[str] = None,
        contract_id: Optional[str] = None,
        strict_require_invoices: bool = False
    ) -> bool:
        """
        Enforces statutory fee collection gating.
        Blocks contract handover, tenancy activation, or deal closure (WON)
        until all statutory Saudi fee invoices are in status 'PAID'.
        """
        invoices = await conn.fetch(
            """
            SELECT invoice_id, invoice_number, payer_type, total_amount, amount_paid, status
            FROM invoices
            WHERE (
                ($1::text IS NOT NULL AND opportunity_id = $1) OR
                ($2::text IS NOT NULL AND lead_id = $2) OR
                ($3::text IS NOT NULL AND contract_id = $3)
            ) AND status != 'CANCELLED'
            """,
            opportunity_id, lead_id, contract_id
        )

        if not invoices:
            if strict_require_invoices:
                raise ValueError("يتطلب النظام إصدار وتحصيل فواتير الرسوم والضرائب النظامية (العميل والمالك) قبل إتمام هذه العملية.")
            return True

        unpaid = [inv for inv in invoices if inv["status"] != "PAID"]
        if unpaid:
            unpaid_details = []
            for inv in unpaid:
                payer = "العميل" if inv["payer_type"] == "CUSTOMER" else "المالك"
                amt = float(inv["total_amount"] or 0)
                unpaid_details.append(f"{inv['invoice_number']} ({payer}: {amt:,.2f} ريال)")
            raise ValueError(
                f"لا يمكن الانتقال للمرحلة التالية أو إغلاق الصفقة قبل تحصيل كافة الرسوم والضرائب النظامية المستحقة (السعي، ضريبة التصرفات العقارية، رسوم إيجار). الفواتير غير المسددة: {', '.join(unpaid_details)}"
            )

        return True

    @staticmethod
    async def process_expired_reservations(conn: asyncpg.Connection) -> Dict[str, Any]:
        """
        Stage F Expiry Engine
        Monitors active reservations approaching expiry or past expiry.
        - If within 12h of expiry: spawns TASK_RESERVATION_EXPIRY_REVIEW for Branch Manager.
        - If past expiry without deposit: cancels reservation, releases unit back to AVAILABLE with unit_status_history.
        """
        now_dt = datetime.now(timezone.utc)
        near_expiry = await conn.fetch(
            """
            SELECT r.*, u.unit_number, o.assigned_user_id
            FROM reservations r
            JOIN units u ON r.unit_id = u.unit_id
            LEFT JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE r.status = 'ACTIVE'
              AND r.expires_at > $1
              AND r.expires_at <= $2
            """,
            now_dt, now_dt + timedelta(hours=12)
        )
        spawned_reviews = []
        for res in near_expiry:
            mgr_id = await conn.fetchval(
                """
                SELECT u.user_id 
                FROM users u
                JOIN user_roles ur ON u.user_id = ur.user_id
                JOIN roles r ON ur.role_id = r.role_id
                WHERE r.role_code IN ('BRANCH_MANAGER', 'SALES_DIRECTOR')
                LIMIT 1
                """
            ) or res["assigned_user_id"]

            rev_task, is_new = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_RESERVATION_EXPIRY_REVIEW",
                opportunity_id=res["opportunity_id"],
                customer_id=res["customer_id"],
                assigned_user_id=mgr_id,
                priority="URGENT",
                custom_due_at=res["expires_at"]
            )
            if is_new:
                spawned_reviews.append(res["reservation_id"])

        expired_rows = await conn.fetch(
            """
            SELECT r.*, u.unit_number
            FROM reservations r
            JOIN units u ON r.unit_id = u.unit_id
            WHERE r.status = 'ACTIVE' AND r.expires_at <= $1
            """,
            now_dt
        )
        cancelled_reservations = []
        for res in expired_rows:
            async with conn.transaction():
                await conn.execute("UPDATE reservations SET status = 'EXPIRED' WHERE reservation_id = $1", res["reservation_id"])
                await conn.execute("UPDATE units SET status = 'AVAILABLE', updated_at = NOW() WHERE unit_id = $1", res["unit_id"])
                hist_id = await get_next_id(conn, "unit_status_history", "ush")
                await conn.execute(
                    """
                    INSERT INTO unit_status_history (
                        unit_status_history_id, unit_id, old_status, new_status,
                        changed_by_user_id, changed_at, reason
                    ) VALUES ($1, $2, 'RESERVED', 'AVAILABLE', NULL, $3, $4)
                    """,
                    hist_id, res["unit_id"], now_dt, f"إلغاء الحجز {res['reservation_number']} لانتهاء المهلة دون سداد العربون"
                )
                cancelled_reservations.append(res["reservation_id"])

        return {
            "approaching_expiry_reviews": spawned_reviews,
            "expired_and_released": cancelled_reservations
        }

    @staticmethod
    async def complete_task_with_outcome(
        conn: asyncpg.Connection,
        task_id: str,
        user_id: str,
        outcome: str,
        notes: Optional[str] = None,
        qualification_data: Optional[Dict[str, Any]] = None,
        viewing_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Completes a task, generates the corresponding Activity, and evaluates
        business status transitions according to authorized business rules.
        """
        task = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found.")

        if task["status"] == "COMPLETED":
            return {"task": dict(task), "already_completed": True}

        now_dt = datetime.now(timezone.utc)

        # 1. Complete Task
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE task_id = $2
            """,
            now_dt, task_id
        )

        tmpl_id = task["template_id"]
        lead_id = task["lead_id"]

        # 2. Stage 2 Special Handling: TASK_LEAD_QUALIFY
        if lead_id and tmpl_id == "TASK_LEAD_QUALIFY":
            if outcome in ("QUALIFIED", "CONVERTED"):
                q_data = qualification_data or {}
                qual_res = await WorkflowEngine.on_lead_qualified(
                    conn=conn,
                    lead_id=lead_id,
                    user_id=user_id,
                    budget_min=q_data.get("budget_min"),
                    budget_max=q_data.get("budget_max"),
                    preferred_property_type_id=q_data.get("preferred_property_type_id"),
                    preferred_city_id=q_data.get("preferred_city_id"),
                    notes=notes,
                    parent_task_id=task_id
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": qual_res["activity"],
                    "business_transition": qual_res
                }
            elif outcome in ("DISQUALIFIED", "NOT_INTERESTED", "LOST"):
                await conn.execute(
                    "UPDATE leads SET status = 'DISQUALIFIED', updated_at = NOW() WHERE lead_id = $1",
                    lead_id
                )
                await conn.execute(
                    "UPDATE opportunities SET stage = 'LOST', updated_at = NOW() WHERE lead_id = $1 AND stage NOT IN ('WON', 'LOST')",
                    lead_id
                )
                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_LEAD_QUALIFIED",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    task_id=task_id,
                    outcome="DISQUALIFIED",
                    notes=notes or "تم استبعاد الطلب لعدم توافر معايير التأهيل أو رغبة العميل.",
                    completed_at=now_dt
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"lead_id": lead_id, "new_status": "DISQUALIFIED"}
                }
            elif outcome in ("NO_ANSWER", "FOLLOWUP_NEEDED", "CALLBACK_REQUESTED"):
                followup_due = now_dt + timedelta(hours=3)
                followup_task, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id="TASK_LEAD_FOLLOWUP",
                    lead_id=lead_id,
                    customer_id=task["customer_id"],
                    assigned_user_id=task["assigned_user_id"] or user_id,
                    custom_due_at=followup_due,
                    priority="NORMAL",
                    parent_task_id=task_id
                )
                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_LEAD_FOLLOWUP",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    task_id=task_id,
                    outcome=outcome,
                    notes=notes or "طلب متابعة إضافية لاستكمال معايير التأهيل.",
                    completed_at=now_dt
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"lead_id": lead_id, "followup_task": followup_task}
                }

        # 3. Stage C Handling: TASK_OPPORTUNITY_MATCH_PROPERTIES & TASK_RENT_MATCH_PROPERTIES
        if tmpl_id in ("TASK_OPPORTUNITY_MATCH_PROPERTIES", "TASK_RENT_MATCH_PROPERTIES"):
            v_data = viewing_data or {}
            unit_ids = v_data.get("unit_ids") or []
            if not unit_ids and v_data.get("unit_id"):
                unit_ids = [v_data.get("unit_id")]
            opp_id = task["opportunity_id"]
            if not opp_id and lead_id:
                opp_id = await conn.fetchval("SELECT opportunity_id FROM opportunities WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 1", lead_id)
            if not opp_id:
                raise ValueError("No opportunity linked to property matching task.")

            if outcome in ("NONE_FOUND", "REVISE_CRITERIA"):
                act_tmpl = "ACT_RENT_PROPERTIES_MATCHED" if tmpl_id == "TASK_RENT_MATCH_PROPERTIES" else "ACT_OPPORTUNITY_PROPERTIES_PRESENTED"
                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id=act_tmpl,
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    opportunity_id=opp_id,
                    task_id=task_id,
                    outcome=outcome,
                    notes=notes or "لم يتم العثور على وحدات شاغرة مطابقة حالياً. سيتم تحديث معايير البحث.",
                    completed_at=now_dt
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"status": "REVISE_CRITERIA"}
                }

            pres_res = await WorkflowEngine.present_opportunity_properties(
                conn=conn,
                user_id=user_id,
                opportunity_id=opp_id,
                unit_ids=unit_ids,
                notes=notes,
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": pres_res["activity"],
                "business_transition": pres_res,
                "viewing_task": pres_res["viewing_task"]
            }

        # 4. Stage D Handling: TASK_VIEWING_SCHEDULE & TASK_VIEWING_RESCHEDULE & TASK_RENT_VIEWING_FOLLOW_UP & TASK_INVEST_SCHEDULE_INSPECTION
        if tmpl_id in ("TASK_VIEWING_SCHEDULE", "TASK_VIEWING_RESCHEDULE", "TASK_RENT_VIEWING_FOLLOW_UP", "TASK_INVEST_SCHEDULE_INSPECTION"):
            v_data = viewing_data or {}
            # If completing viewing follow up with inspection outcome directly:
            if tmpl_id == "TASK_RENT_VIEWING_FOLLOW_UP" and outcome in ("INTERESTED", "NOT_INTERESTED", "NEEDS_ANOTHER_UNIT", "NO_SHOW", "CANCELLED") and not v_data.get("scheduled_start"):
                res = await WorkflowEngine.complete_property_viewing_report(
                    conn=conn,
                    task_id=task_id,
                    user_id=user_id,
                    outcome=outcome,
                    feedback_notes=notes or v_data.get("location_notes"),
                    offer_amount=v_data.get("offer_amount")
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": res["activity"],
                    "business_transition": res,
                    "viewing_id": res.get("viewing_id"),
                    "new_stage": res.get("new_stage"),
                    "next_action": res.get("next_action")
                }

            unit_id = v_data.get("unit_id")
            if not unit_id:
                if lead_id:
                    unit_id = await conn.fetchval(
                        "SELECT unit_id FROM lead_units WHERE lead_id = $1 ORDER BY is_primary DESC, created_at ASC LIMIT 1",
                        lead_id
                    )
                if not unit_id and task["opportunity_id"]:
                    unit_id = await conn.fetchval(
                        "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                        task["opportunity_id"]
                    )
                if not unit_id and lead_id:
                    unit_id = await conn.fetchval("SELECT unit_id FROM leads WHERE lead_id = $1", lead_id)
                if not unit_id:
                    unit_id = await conn.fetchval("SELECT unit_id FROM units WHERE status = 'AVAILABLE' LIMIT 1") or "unit-2"

            sch_start = v_data.get("scheduled_start")
            if isinstance(sch_start, str):
                sch_start = datetime.fromisoformat(sch_start.replace("Z", "+00:00"))
            elif not sch_start:
                sch_start = now_dt + timedelta(days=1, hours=2)

            sch_end = v_data.get("scheduled_end")
            if isinstance(sch_end, str):
                sch_end = datetime.fromisoformat(sch_end.replace("Z", "+00:00"))
            elif not sch_end:
                dur = v_data.get("viewing_duration_minutes") or 45
                sch_end = sch_start + timedelta(minutes=dur)

            res = await WorkflowEngine.schedule_property_viewing(
                conn=conn,
                user_id=user_id,
                unit_id=unit_id,
                scheduled_start=sch_start,
                scheduled_end=sch_end,
                task_id=task_id,
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                customer_id=task["customer_id"],
                agent_user_id=task["assigned_user_id"] or user_id,
                notes=notes,
                location_notes=v_data.get("location_notes")
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res,
                "viewing_id": res.get("viewing_id"),
                "new_stage": res.get("new_stage")
            }

        if tmpl_id == "TASK_VIEWING_REPORT":
            v_data = viewing_data or {}
            try:
                res = await WorkflowEngine.complete_property_viewing_report(
                    conn=conn,
                    task_id=task_id,
                    user_id=user_id,
                    outcome=outcome,
                    feedback_notes=notes or v_data.get("location_notes"),
                    offer_amount=v_data.get("offer_amount")
                )
            except Exception:
                await conn.execute(
                    "UPDATE tasks SET status = $1, completed_at = $2 WHERE task_id = $3",
                    task["status"], task["completed_at"], task_id
                )
                raise
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res,
                "viewing_id": res.get("viewing_id"),
                "new_stage": res.get("new_stage"),
                "next_action": res.get("next_action")
            }

        # 5. Stage E Handling: Offers & Negotiation
        if tmpl_id in ("TASK_OFFER_PREPARE", "TASK_OFFER_SUBMIT"):
            v_data = viewing_data or {}
            unit_id = v_data.get("unit_id")
            if not unit_id and task["opportunity_id"]:
                unit_id = await conn.fetchval(
                    "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not unit_id:
                unit_id = await conn.fetchval("SELECT unit_id FROM units WHERE status = 'AVAILABLE' LIMIT 1") or "unit-2"

            offer_amt = None
            if v_data.get("offer_amount"):
                try:
                    offer_amt = float(v_data["offer_amount"])
                except (ValueError, TypeError):
                    offer_amt = None

            if (not offer_amt or offer_amt <= 0) and task["opportunity_id"]:
                opp_row = await conn.fetchrow(
                    "SELECT expected_value, deal_value FROM opportunities WHERE opportunity_id = $1",
                    task["opportunity_id"]
                )
                if opp_row:
                    offer_amt = float(opp_row["expected_value"] or opp_row["deal_value"] or 0)

            if (not offer_amt or offer_amt <= 0) and unit_id:
                u_row = await conn.fetchrow(
                    "SELECT asking_price, rent_price FROM units WHERE unit_id = $1",
                    unit_id
                )
                if u_row:
                    offer_amt = float(u_row["asking_price"] or u_row["rent_price"] or 0)

            # Cap inferred offer_amt at unit price if it came from expected_value or budget_max
            if unit_id and (not v_data.get("offer_amount")):
                u_row = await conn.fetchrow("SELECT asking_price, rent_price FROM units WHERE unit_id = $1", unit_id)
                unit_price = float((u_row["asking_price"] if u_row else None) or (u_row["rent_price"] if u_row else None) or 0)
                if unit_price > 0 and offer_amt and offer_amt > unit_price:
                    offer_amt = unit_price

            if (not offer_amt or offer_amt <= 0) and task["lead_id"]:
                l_row = await conn.fetchrow(
                    "SELECT budget_max, budget_min FROM leads WHERE lead_id = $1",
                    task["lead_id"]
                )
                if l_row:
                    offer_amt = float(l_row["budget_max"] or l_row["budget_min"] or 0)

            if not offer_amt or offer_amt <= 0:
                offer_amt = 500000.0

            try:
                res = await WorkflowEngine.submit_commercial_offer(
                    conn=conn,
                    opportunity_id=task["opportunity_id"],
                    unit_id=unit_id,
                    offer_amount=offer_amt,
                    valid_until=v_data.get("valid_until"),
                    user_id=user_id,
                    notes=notes,
                    parent_task_id=task_id
                )
            except Exception:
                await conn.execute(
                    "UPDATE tasks SET status = $1, completed_at = $2 WHERE task_id = $3",
                    task["status"], task["completed_at"], task_id
                )
                raise
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        if tmpl_id == "TASK_OFFER_MANAGER_APPROVAL":
            v_data = viewing_data or {}
            offer_id = v_data.get("offer_id")
            if not offer_id and task["opportunity_id"]:
                offer_id = await conn.fetchval(
                    "SELECT offer_id FROM offers WHERE opportunity_id = $1 ORDER BY submitted_at DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not offer_id:
                raise ValueError("No offer record found to approve.")

            decision = "APPROVED" if outcome.strip().upper() in ("APPROVED", "ACCEPT", "APPROVE") else "REJECTED"
            res = await WorkflowEngine.record_offer_decision(
                conn=conn,
                offer_id=offer_id,
                decision=decision,
                notes=notes,
                user_id=user_id,
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        if tmpl_id == "TASK_OFFER_FOLLOWUP":
            v_data = viewing_data or {}
            offer_id = v_data.get("offer_id")
            if not offer_id and task["opportunity_id"]:
                offer_id = await conn.fetchval(
                    "SELECT offer_id FROM offers WHERE opportunity_id = $1 ORDER BY submitted_at DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not offer_id:
                raise ValueError("No offer record found to resolve.")

            counter_amt = float(v_data.get("counter_amount")) if v_data.get("counter_amount") else None
            res = await WorkflowEngine.record_offer_decision(
                conn=conn,
                offer_id=offer_id,
                decision=outcome.strip().upper(),
                counter_amount=counter_amt,
                notes=notes,
                user_id=user_id,
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        # 6. Stage F Handling: Reservation & Financial Coordination
        if tmpl_id == "TASK_RESERVATION_VERIFY_AVAILABILITY":
            v_data = viewing_data or {}
            unit_id = v_data.get("unit_id")
            if not unit_id and task["opportunity_id"]:
                unit_id = await conn.fetchval(
                    "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not unit_id:
                unit_id = await conn.fetchval(
                    "SELECT unit_id FROM offers WHERE opportunity_id = $1 AND status = 'ACCEPTED' ORDER BY submitted_at DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not unit_id:
                unit_id = await conn.fetchval("SELECT unit_id FROM units WHERE status = 'AVAILABLE' LIMIT 1") or "unit-2"

            deposit_amt = float(v_data.get("deposit_amount")) if v_data.get("deposit_amount") else None
            exp_hrs = int(v_data.get("expiry_hours") or 48)

            res = await WorkflowEngine.create_unit_reservation(
                conn=conn,
                opportunity_id=task["opportunity_id"],
                unit_id=unit_id,
                customer_id=task["customer_id"],
                deposit_amount=deposit_amt,
                expiry_hours=exp_hrs,
                user_id=user_id,
                parent_task_id=task_id,
                notes=notes
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        if tmpl_id == "TASK_RESERVATION_DEPOSIT_FOLLOWUP":
            v_data = viewing_data or {}
            res_id = v_data.get("reservation_id")
            if not res_id and task["opportunity_id"]:
                res_id = await conn.fetchval(
                    "SELECT reservation_id FROM reservations WHERE opportunity_id = $1 ORDER BY reserved_at DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not res_id:
                raise ValueError("No reservation linked to deposit task.")

            norm_outcome = outcome.strip().upper()
            if norm_outcome in ("DEPOSIT_VERIFIED", "VERIFIED", "PAID"):
                amt = float(v_data.get("amount_received") or v_data.get("deposit_amount") or 25000.0)
                method = v_data.get("payment_method") or "BANK_TRANSFER"
                ref = v_data.get("payment_reference") or "DEP-VERIFIED"
                res = await WorkflowEngine.verify_reservation_deposit(
                    conn=conn,
                    reservation_id=res_id,
                    amount_received=amt,
                    payment_method=method,
                    payment_ref=ref,
                    user_id=user_id,
                    notes=notes,
                    parent_task_id=task_id
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": res["activity"],
                    "business_transition": res
                }
            elif norm_outcome in ("CANCELLED", "CANCEL"):
                res_row = await conn.fetchrow("SELECT unit_id, reservation_number FROM reservations WHERE reservation_id = $1", res_id)
                await conn.execute("UPDATE reservations SET status = 'CANCELLED' WHERE reservation_id = $1", res_id)
                await conn.execute("UPDATE units SET status = 'AVAILABLE', updated_at = NOW() WHERE unit_id = $1", res_row["unit_id"])
                hist_id = await get_next_id(conn, "unit_status_history", "ush")
                await conn.execute(
                    """
                    INSERT INTO unit_status_history (
                        unit_status_history_id, unit_id, old_status, new_status,
                        changed_by_user_id, changed_at, reason
                    ) VALUES ($1, $2, 'RESERVED', 'AVAILABLE', $3, NOW(), $4)
                    """,
                    hist_id, res_row["unit_id"], user_id, f"إلغاء الحجز {res_row['reservation_number']}"
                )
                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_RESERVATION_CONFIRMED",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    opportunity_id=task["opportunity_id"],
                    task_id=task_id,
                    outcome="CANCELLED",
                    notes=notes or "تم إلغاء الحجز وتحرير الوحدة في المخزون.",
                    completed_at=now_dt
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"status": "CANCELLED"}
                }

        # 7. Stage G Handling: Contract Preparation, Signing and Closure
        if tmpl_id == "TASK_CONTRACT_DRAFT":
            v_data = viewing_data or {}
            res_id = v_data.get("reservation_id")
            if not res_id and task["opportunity_id"]:
                res_id = await conn.fetchval(
                    "SELECT reservation_id FROM reservations WHERE opportunity_id = $1 ORDER BY reserved_at DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not res_id:
                raise ValueError("No reservation linked to contract draft task.")

            c_type = v_data.get("contract_type") or "SALE"
            c_val = float(v_data.get("contract_value")) if v_data.get("contract_value") else None
            res = await WorkflowEngine.initiate_contract_draft(
                conn=conn,
                reservation_id=res_id,
                contract_type=c_type,
                contract_value=c_val,
                user_id=user_id,
                notes=notes,
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        if tmpl_id == "TASK_CONTRACT_INTERNAL_REVIEW":
            v_data = viewing_data or {}
            contract_id = v_data.get("contract_id")
            if not contract_id and task["opportunity_id"]:
                contract_id = await conn.fetchval(
                    """
                    SELECT c.contract_id 
                    FROM contracts c 
                    JOIN reservations r ON c.reservation_id = r.reservation_id 
                    WHERE r.opportunity_id = $1 
                    ORDER BY c.signed_at DESC NULLS LAST, c.contract_id DESC LIMIT 1
                    """,
                    task["opportunity_id"]
                )
            if not contract_id:
                raise ValueError("No contract linked to review task.")

            res = await WorkflowEngine.advance_contract_lifecycle(
                conn=conn,
                contract_id=contract_id,
                action="APPROVE_DRAFT",
                user_id=user_id,
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        if tmpl_id == "TASK_CONTRACT_SIGNATURE":
            v_data = viewing_data or {}
            contract_id = v_data.get("contract_id")
            if not contract_id and task["opportunity_id"]:
                contract_id = await conn.fetchval(
                    """
                    SELECT c.contract_id 
                    FROM contracts c 
                    JOIN reservations r ON c.reservation_id = r.reservation_id 
                    WHERE r.opportunity_id = $1 
                    ORDER BY c.signed_at DESC NULLS LAST, c.contract_id DESC LIMIT 1
                    """,
                    task["opportunity_id"]
                )
            if not contract_id:
                raise ValueError("No contract linked to signature task.")

            res = await WorkflowEngine.advance_contract_lifecycle(
                conn=conn,
                contract_id=contract_id,
                action="RECORD_SIGNATURE",
                user_id=user_id,
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        if tmpl_id == "TASK_CONTRACT_HANDOVER":
            v_data = viewing_data or {}
            contract_id = v_data.get("contract_id")
            if not contract_id and task["opportunity_id"]:
                contract_id = await conn.fetchval(
                    """
                    SELECT c.contract_id 
                    FROM contracts c 
                    JOIN reservations r ON c.reservation_id = r.reservation_id 
                    WHERE r.opportunity_id = $1 
                    ORDER BY c.signed_at DESC NULLS LAST, c.contract_id DESC LIMIT 1
                    """,
                    task["opportunity_id"]
                )
            if not contract_id:
                raise ValueError("No contract linked to handover task.")

            res = await WorkflowEngine.advance_contract_lifecycle(
                conn=conn,
                contract_id=contract_id,
                action="COMPLETE_HANDOVER",
                user_id=user_id,
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": res["activity"],
                "business_transition": res
            }

        # Rental Pipeline Stage Handling: TASK_RENT_PREPARE_TENANCY
        if tmpl_id == "TASK_RENT_PREPARE_TENANCY":
            v_data = viewing_data or {}
            norm_outcome = outcome.strip().upper()
            if norm_outcome in ("EXECUTED", "AGREEMENT_EXECUTED", "COMPLETED", "APPROVED"):
                unit_id = v_data.get("unit_id")
                if not unit_id and task["opportunity_id"]:
                    unit_id = await conn.fetchval(
                        "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                        task["opportunity_id"]
                    )
                if not unit_id and lead_id:
                    unit_id = await conn.fetchval("SELECT unit_id FROM leads WHERE lead_id = $1", lead_id)
                if not unit_id:
                    unit_id = await conn.fetchval("SELECT unit_id FROM units WHERE status = 'AVAILABLE' LIMIT 1") or "unit-2"

                rent_amt = v_data.get("rent_amount")
                if rent_amt is None and unit_id:
                    rent_amt = await conn.fetchval("SELECT rent_price FROM units WHERE unit_id = $1", unit_id)
                rent_amt = float(rent_amt or 30000.0)

                s_date = v_data.get("start_date") or date.today()
                e_date = v_data.get("end_date")
                freq = v_data.get("payment_frequency") or "ANNUAL"
                dep = float(v_data.get("deposit_amount") or 0.0)
                inst_cnt = int(v_data.get("installments_count") or 1)
                c_num = v_data.get("contract_number")

                res = await WorkflowEngine.execute_tenancy_agreement(
                    conn=conn,
                    unit_id=unit_id,
                    tenant_customer_id=task["customer_id"],
                    start_date=s_date,
                    end_date=e_date,
                    rent_amount=rent_amt,
                    payment_frequency=freq,
                    deposit_amount=dep,
                    contract_number=c_num,
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    user_id=user_id,
                    generate_installments=True,
                    installments_count=inst_cnt,
                    parent_task_id=task_id,
                    notes=notes
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": res["activity"],
                    "business_transition": res
                }
            elif norm_outcome in ("REJECTED", "TERMS_REJECTED", "CANCELLED"):
                match_task, _ = await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id="TASK_RENT_MATCH_PROPERTIES",
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    customer_id=task["customer_id"],
                    assigned_user_id=task["assigned_user_id"] or user_id,
                    priority="NORMAL",
                    parent_task_id=task_id
                )
                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_RENT_PROPERTIES_MATCHED",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    task_id=task_id,
                    outcome=outcome,
                    notes=notes or "تم رفض شروط عقد الإيجار المقترح. تم إعادة فتح مسار مطابقة وترشيح وحدات بديلة.",
                    completed_at=now_dt
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"type": "RENT_MATCH_SPAWNED", "task": match_task}
                }

        # Rental Pipeline Handling: TASK_RENT_COLLECTION_MONITORING
        if tmpl_id == "TASK_RENT_COLLECTION_MONITORING":
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_RENT_PAYMENT_COLLECTED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome=outcome,
                notes=notes or "تمت مراجعة ومتابعة جدول دفعات الإيجار المستحقة.",
                completed_at=now_dt
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {"status": "MONITORED"}
            }

        # =========================================================================
        # Investment Pipeline Handling: Phase 3
        # =========================================================================

        # 1. TASK_INVEST_CONFIRM_OBJECTIVES
        if tmpl_id == "TASK_INVEST_CONFIRM_OBJECTIVES":
            v_data = viewing_data or {}
            q_data = qualification_data or {}
            t_cap = v_data.get("purchase_price") or v_data.get("target_capital") or q_data.get("budget_max")
            if not t_cap or float(t_cap) == 0.0:
                if lead_id:
                    t_cap = await conn.fetchval("SELECT budget_max FROM leads WHERE lead_id = $1", lead_id)
                if (not t_cap or float(t_cap) == 0.0) and task.get("opportunity_id"):
                    t_cap = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", task["opportunity_id"])
            t_cap = float(t_cap or 0.0)

            t_yield = float(v_data.get("target_yield_percent") or 8.0)
            horizon = int(v_data.get("investment_horizon_years") or 5)
            risk = (v_data.get("risk_tolerance") or "MEDIUM").upper()
            strat = (v_data.get("investment_strategy") or "BALANCED").upper()

            # Ensure lead and opportunity budget/value are synchronized with the confirmed target capital
            if t_cap > 0:
                if lead_id:
                    await conn.execute("UPDATE leads SET budget_max = $1, updated_at = NOW() WHERE lead_id = $2", t_cap, lead_id)
                if task.get("opportunity_id"):
                    await conn.execute("UPDATE opportunities SET expected_value = $1, updated_at = NOW() WHERE opportunity_id = $2", t_cap, task["opportunity_id"])

            cand_unit_ids = list(v_data.get("unit_ids") or [])
            if v_data.get("unit_id") and v_data["unit_id"] not in cand_unit_ids:
                cand_unit_ids.append(v_data["unit_id"])
            if cand_unit_ids and task["opportunity_id"]:
                for idx, uid in enumerate(cand_unit_ids):
                    await conn.execute(
                        """
                        INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                        SELECT $1::varchar, $2::varchar, $3::boolean, COALESCE(asking_price, rent_price, 0)
                        FROM units WHERE unit_id = $2::varchar
                        ON CONFLICT (opportunity_id, unit_id) DO NOTHING
                        """,
                        task["opportunity_id"], uid, (idx == 0)
                    )

            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            crit_summary = (
                f"تم اعتماد وتأكيد الأهداف الاستثمارية: رأس المال المستهدف: {t_cap:,.2f} ريال | "
                f"العائد المستهدف: {t_yield}% | الأفق الزمني: {horizon} سنوات | "
                f"تحمل المخاطر: {risk} | الإستراتيجية: {strat}."
            )
            obj_notes = f"{crit_summary} {notes}" if notes else crit_summary
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_INVEST_OBJECTIVES_CONFIRMED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome=outcome,
                notes=obj_notes,
                completed_at=now_dt
            )

            next_task = await WorkflowEngine.spawn_next_workflow_task(
                conn=conn,
                current_task=dict(task),
                outcome=outcome,
                user_id=user_id,
                priority="HIGH",
                parent_task_id=task_id
            )

            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {
                    "type": "INVEST_OBJECTIVES_CONFIRMED",
                    "opportunity_id": task["opportunity_id"],
                    "next_task": next_task
                }
            }

        # 2. TASK_INVEST_COMPARE_RETURNS
        if tmpl_id == "TASK_INVEST_COMPARE_RETURNS":
            v_data = viewing_data or {}
            sel_unit_id = v_data.get("unit_id")
            p_price = float(v_data.get("purchase_price") or 0.0)
            m_rent = float(v_data.get("monthly_rent_forecast") or 0.0)
            if m_rent == 0.0 and v_data.get("gross_annual_rent"):
                m_rent = float(v_data["gross_annual_rent"]) / 12.0
            vac = float(v_data.get("annual_vacancy_allowance") or 0.0)
            opex = float(v_data.get("annual_operating_expenses") or 0.0)
            acq = float(v_data.get("acquisition_costs") or 0.0)
            cash_inv = float(v_data.get("cash_invested") or (p_price if p_price > 0 else 1.0))
            cf = float(v_data.get("annual_pre_tax_cash_flow") or max(0.0, (m_rent * 12.0) - vac - opex))

            if sel_unit_id and p_price == 0.0:
                u_row = await conn.fetchrow("SELECT asking_price, rent_price FROM units WHERE unit_id = $1", sel_unit_id)
                if u_row:
                    p_price = float(u_row["asking_price"] or 0.0)
                    if m_rent == 0.0:
                        m_rent = float(u_row["rent_price"] or (p_price * 0.08 / 12.0))
                    if cash_inv <= 1.0 and p_price > 0:
                        cash_inv = p_price
                    if cf == 0.0:
                        cf = max(0.0, (m_rent * 12.0) - vac - opex)

            if p_price == 0.0:
                if lead_id:
                    p_price = float(await conn.fetchval("SELECT budget_max FROM leads WHERE lead_id = $1", lead_id) or 0.0)
                if p_price == 0.0 and task.get("opportunity_id"):
                    p_price = float(await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", task["opportunity_id"]) or 0.0)
                if cash_inv <= 1.0 and p_price > 0:
                    cash_inv = p_price
                if m_rent == 0.0 and p_price > 0:
                    m_rent = (p_price * 0.08) / 12.0
                if opex == 0.0 and m_rent > 0:
                    opex = (m_rent * 12.0) * 0.10
                if vac == 0.0 and m_rent > 0:
                    vac = (m_rent * 12.0) * 0.05
                if cf == 0.0:
                    cf = max(0.0, (m_rent * 12.0) - vac - opex)

            from app.services.calculation_service import CalculationService
            rental_metrics = CalculationService.calculate_rental_metrics(
                monthly_rent=m_rent,
                purchase_price=p_price,
                annual_vacancy_allowance=vac,
                annual_operating_expenses=opex,
                acquisition_costs=acq
            )
            invest_returns = CalculationService.calculate_investment_returns(
                purchase_price=p_price,
                cash_invested=cash_inv,
                annual_pre_tax_cash_flow=cf
            )

            if sel_unit_id and task["opportunity_id"]:
                await conn.execute(
                    """
                    INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                    VALUES ($1, $2, TRUE, $3)
                    ON CONFLICT (opportunity_id, unit_id) DO UPDATE SET is_primary = TRUE, offered_price = EXCLUDED.offered_price
                    """,
                    task["opportunity_id"], sel_unit_id, p_price
                )
                await conn.execute(
                    "UPDATE opportunity_units SET is_primary = FALSE WHERE opportunity_id = $1 AND unit_id != $2",
                    task["opportunity_id"], sel_unit_id
                )
                await conn.execute(
                    "UPDATE opportunities SET expected_value = $1, updated_at = NOW() WHERE opportunity_id = $2",
                    p_price, task["opportunity_id"]
                )

            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            comp_notes = notes or (
                f"تمت دراسة ومقارنة العوائد الاستثمارية للوحدة ({sel_unit_id or 'المرشحة'}): "
                f"سعر الشراء: {p_price:,.2f} ريال | العائد الإجمالي: {rental_metrics['gross_yield_percent']}% | "
                f"عائد التشغيل الصافي: {rental_metrics['net_operating_yield_percent']}% | "
                f"صافي الدخل التشغيلي (NOI): {rental_metrics['net_operating_income']:,.2f} ريال | "
                f"العائد على النقد المستثمر (CoC): {invest_returns['cash_on_cash_return_percent']}%."
            )
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_INVEST_RETURNS_COMPARED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome=outcome,
                notes=comp_notes,
                completed_at=now_dt
            )

            next_task = await WorkflowEngine.spawn_next_workflow_task(
                conn=conn,
                current_task=dict(task),
                outcome=outcome,
                user_id=user_id,
                priority="HIGH",
                parent_task_id=task_id
            )

            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {
                    "type": "INVEST_RETURNS_COMPARED",
                    "metrics": rental_metrics,
                    "returns": invest_returns,
                    "next_task": next_task
                }
            }

        # 3. TASK_INVEST_INSPECTION_REPORT: Complete Technical & Commercial Due Diligence Report
        if tmpl_id == "TASK_INVEST_INSPECTION_REPORT":
            v_data = viewing_data or {}
            norm_outcome = (outcome or "RECOMMENDED").upper()
            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            # 1. Resolve unit_id
            target_unit_id = v_data.get("unit_id")
            if not target_unit_id and task["opportunity_id"]:
                target_unit_id = await conn.fetchval(
                    "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not target_unit_id and lead_id:
                target_unit_id = await conn.fetchval("SELECT unit_id FROM leads WHERE lead_id = $1", lead_id)
            if not target_unit_id:
                target_unit_id = await conn.fetchval("SELECT unit_id FROM units LIMIT 1") or "unit-1"

            # 2. Extract Technical Due Diligence Fields
            struct_cond = v_data.get("structural_condition") or "GOOD"
            bld_age = int(v_data.get("building_age_years") or 5)
            sbc_compliant = bool(v_data.get("saudi_building_code_compliant") if v_data.get("saudi_building_code_compliant") is not None else True)
            hvac_st = v_data.get("hvac_status") or "OPERATIONAL"
            elev_st = v_data.get("elevators_status") or "OPERATIONAL"
            plumb_st = v_data.get("plumbing_network_status") or "GOOD"
            elec_st = v_data.get("electrical_network_status") or "GOOD"
            roof_st = v_data.get("roofing_and_insulation_status") or "GOOD"
            fire_st = v_data.get("fire_safety_compliance") or "COMPLIANT"
            est_capex = float(v_data.get("estimated_capex_sar") or 0.0)
            tech_notes = v_data.get("technical_notes") or notes

            # 3. Extract Commercial & Occupancy Fields
            traffic_flow = v_data.get("location_traffic_flow") or "HIGH"
            access_quality = v_data.get("access_and_egress_quality") or "GOOD"
            parking_avail = v_data.get("parking_availability") or "ADEQUATE"
            actual_occ = float(v_data.get("actual_occupancy_rate") if v_data.get("actual_occupancy_rate") is not None else 95.0)
            tot_inspected = int(v_data.get("total_units_inspected") or 1)
            occ_count = int(v_data.get("occupied_units_count") or 1)
            vac_count = int(v_data.get("vacant_units_count") or 0)
            rent_roll_ver = bool(v_data.get("rent_roll_verified") if v_data.get("rent_roll_verified") is not None else True)
            pm_notes = v_data.get("property_manager_interview_notes")
            comm_score = int(v_data.get("commercial_viability_score") or 85)
            comm_notes = v_data.get("commercial_notes")

            # 4. Extract Overall Recommendation
            rec = v_data.get("recommendation")
            if not rec:
                rec = "REJECTED" if norm_outcome in ("REJECTED", "CANCELLED", "NOT_INTERESTED") else "RECOMMENDED"
            price_adj = float(v_data.get("suggested_price_adjustment_sar") or 0.0)
            verdict_summary = v_data.get("final_verdict_summary") or notes

            # 4.5. Compute Financial Metrics (NOI, Cap Rate, Net Yield, CoC, OPEX, Vacancy Allowance)
            from app.services.calculation_service import CalculationService
            p_price = float(v_data.get("purchase_price") or 0.0)
            # Prioritize Unit Asking Price over general Opportunity expected value / Lead budget
            if p_price <= 0.0 and target_unit_id:
                u_price = await conn.fetchval("SELECT asking_price FROM units WHERE unit_id = $1", target_unit_id)
                if u_price and float(u_price) > 0:
                    p_price = float(u_price)
            if p_price <= 0.0 and task["opportunity_id"]:
                opp_v = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", task["opportunity_id"])
                p_price = float(opp_v or 0.0)

            # Monthly rent & Gross Annual rent resolution
            gross_annual_rent = float(v_data.get("gross_annual_rent") or 0.0)
            m_rent = float(v_data.get("monthly_rent_forecast") or 0.0)
            if m_rent <= 0.0 and gross_annual_rent > 0.0:
                m_rent = gross_annual_rent / 12.0
            elif m_rent > 0.0 and gross_annual_rent <= 0.0:
                gross_annual_rent = m_rent * 12.0
            elif m_rent <= 0.0 and gross_annual_rent <= 0.0:
                if target_unit_id:
                    u_rent = await conn.fetchval("SELECT rent_price FROM units WHERE unit_id = $1", target_unit_id)
                    if u_rent and float(u_rent) > 0:
                        m_rent = float(u_rent) / 12.0 if float(u_rent) > 50000 else float(u_rent)
                        gross_annual_rent = m_rent * 12.0
                if m_rent <= 0.0 and p_price > 0.0:
                    gross_annual_rent = p_price * 0.08
                    m_rent = gross_annual_rent / 12.0

            if "annual_vacancy_allowance" in v_data and v_data["annual_vacancy_allowance"] is not None:
                vac_allowance = float(v_data["annual_vacancy_allowance"])
            else:
                vac_percent = max(0.0, 100.0 - actual_occ)
                vac_allowance = gross_annual_rent * (vac_percent / 100.0)

            if "annual_operating_expenses" in v_data and v_data["annual_operating_expenses"] is not None:
                opex = float(v_data["annual_operating_expenses"])
            else:
                opex = gross_annual_rent * 0.10

            cash_inv = float(v_data.get("cash_invested") or (p_price if p_price > 0 else 1.0))

            r_metrics = CalculationService.calculate_rental_metrics(
                monthly_rent=m_rent,
                purchase_price=p_price,
                annual_vacancy_allowance=vac_allowance,
                annual_operating_expenses=opex,
                acquisition_costs=est_capex
            )
            i_returns = CalculationService.calculate_investment_returns(
                purchase_price=p_price,
                cash_invested=cash_inv,
                annual_pre_tax_cash_flow=r_metrics["net_operating_income"]
            )

            eff_gross_income = r_metrics["effective_annual_rent"]
            noi = r_metrics["net_operating_income"]
            tot_basis = r_metrics["total_investment_basis"]
            gross_yield = r_metrics["gross_yield_percent"]
            cap_rate = round((noi / p_price * 100.0), 2) if p_price > 0 else 0.0
            net_yield = r_metrics["net_operating_yield_percent"]
            coc_return = i_returns["cash_on_cash_return_percent"]

            # 5. Insert into investment_due_diligence_reports
            report_id = await get_next_id(conn, "investment_due_diligence_reports", "ddr")
            viewing_id = await conn.fetchval(
                "SELECT viewing_id FROM viewings WHERE opportunity_id = $1 ORDER BY scheduled_start DESC LIMIT 1",
                task["opportunity_id"]
            )
            await conn.execute(
                """
                INSERT INTO investment_due_diligence_reports (
                    report_id, opportunity_id, unit_id, viewing_id, inspector_user_id, inspection_date,
                    structural_condition, building_age_years, saudi_building_code_compliant,
                    hvac_status, elevators_status, plumbing_network_status, electrical_network_status,
                    roofing_and_insulation_status, fire_safety_compliance, estimated_capex_sar, technical_notes,
                    location_traffic_flow, access_and_egress_quality, parking_availability,
                    actual_occupancy_rate, total_units_inspected, occupied_units_count, vacant_units_count,
                    rent_roll_verified, property_manager_interview_notes, commercial_viability_score, commercial_notes,
                    recommendation, suggested_price_adjustment_sar, final_verdict_summary,
                    purchase_price_sar, gross_annual_rent_sar, vacancy_allowance_sar, effective_gross_income_sar,
                    operating_expenses_opex_sar, net_operating_income_noi_sar, total_investment_basis_sar,
                    gross_yield_percent, cap_rate_percent, net_yield_percent, cash_invested_sar, cash_on_cash_return_percent,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, NOW(),
                    $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
                    $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27,
                    $28, $29, $30,
                    $31, $32, $33, $34, $35, $36, $37, $38, $39, $40, $41, $42,
                    NOW(), NOW()
                )
                """,
                report_id, task["opportunity_id"], target_unit_id, viewing_id, user_id,
                struct_cond, bld_age, sbc_compliant,
                hvac_st, elev_st, plumb_st, elec_st,
                roof_st, fire_st, est_capex, tech_notes,
                traffic_flow, access_quality, parking_avail,
                actual_occ, tot_inspected, occ_count, vac_count,
                rent_roll_ver, pm_notes, comm_score, comm_notes,
                rec, price_adj, verdict_summary,
                p_price, gross_annual_rent, vac_allowance, eff_gross_income,
                opex, noi, tot_basis,
                gross_yield, cap_rate, net_yield, cash_inv, coc_return
            )

            # 5.1 Automatically Archive Due Diligence Report to Documents Vault
            await WorkflowEngine.archive_workflow_document(
                conn=conn,
                doc_type_code="DUE_DILIGENCE_REPORT",
                file_name=f"تقرير_الفحص_الفني_والاستثماري_النافي_للجهالة_{report_id}.pdf",
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                unit_id=target_unit_id,
                customer_id=task["customer_id"],
                notes=f"تقرير الفحص الفني والاستثماري - CapEx المقدر: {est_capex:,.2f} ريال",
                metadata={
                    "report_ref": report_id,
                    "structural_condition": struct_cond,
                    "saudi_building_code_compliant": sbc_compliant,
                    "estimated_capex_sar": est_capex,
                    "suggested_price_adjustment_sar": price_adj,
                    "recommendation": rec,
                    "occupied_units": occ_count,
                    "total_units": tot_inspected,
                    "gross_rent": gross_annual_rent,
                    "target_noi": noi,
                    "cap_rate": cap_rate,
                    "asking_price": p_price
                },
                user_id=user_id
            )

            # 6. Record Activity ACT_INVEST_INSPECTION_COMPLETED
            act_notes = (
                f"تم اكتمال تقرير الفحص الفني والاستثماري النافي للجهالة (#{report_id}): "
                f"الهيكل: {struct_cond} | الكود السعودي: {'مطابق' if sbc_compliant else 'غير مطابق'} | "
                f"CapEx تقديري: {est_capex:,.2f} ريال | إشغال فعلي: {actual_occ}% | "
                f"صافي الدخل (NOI): {noi:,.2f} ريال سنوياً | معدل الرسملة: {cap_rate}% | "
                f"صافي العائد بعد CapEx: {net_yield}% | العائد على النقد (CoC): {coc_return}% | "
                f"التوصية الاستثمارية: {rec}."
            )
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_INVEST_INSPECTION_COMPLETED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome=rec,
                notes=act_notes,
                completed_at=now_dt
            )

            # 7. Update viewing record if present
            if viewing_id:
                await conn.execute(
                    "UPDATE viewings SET status = 'COMPLETED', outcome = $1, notes = COALESCE(notes || E'\\n', '') || $2 WHERE viewing_id = $3",
                    rec, act_notes, viewing_id
                )

            # 8. Route to Next Stage via Dynamic Database Transitions:
            next_task = await WorkflowEngine.spawn_next_workflow_task(
                conn=conn,
                current_task=dict(task),
                outcome=rec,
                user_id=user_id,
                priority="HIGH" if rec != "REJECTED" else "NORMAL",
                parent_task_id=task_id
            )
            if rec != "REJECTED":
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {
                        "type": "INVEST_INSPECTION_COMPLETED",
                        "report_id": report_id,
                        "recommendation": rec,
                        "estimated_capex_sar": est_capex,
                        "actual_occupancy_rate": actual_occ,
                        "next_task": next_task
                    }
                }
            else:
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {
                        "type": "INVEST_INSPECTION_REJECTED",
                        "report_id": report_id,
                        "recommendation": rec,
                        "next_task": next_task
                    }
                }

        # 4. TASK_INVEST_VALIDATE_FINANCIALS
        if tmpl_id == "TASK_INVEST_VALIDATE_FINANCIALS":
            norm_outcome = (outcome or "VALIDATED").upper()
            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            # Check if there is an inspection report to enrich validation notes
            rep_row = await conn.fetchrow(
                "SELECT estimated_capex_sar, actual_occupancy_rate, recommendation FROM investment_due_diligence_reports WHERE opportunity_id = $1 ORDER BY created_at DESC LIMIT 1",
                task["opportunity_id"]
            )
            enrich_note = ""
            if rep_row:
                enrich_note = f" (مدعماً بتقرير الفحص الفني: CapEx تقديري {float(rep_row['estimated_capex_sar']):,.2f} ريال | إشغال فعلي {float(rep_row['actual_occupancy_rate'])}% | توصية {rep_row['recommendation']})"

            if norm_outcome in ("VALIDATED", "APPROVED", "CONNECTED", "COMPLETED"):
                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_INVEST_FINANCIALS_VALIDATED",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    task_id=task_id,
                    outcome="VALIDATED",
                    notes=(notes or "تم تدقيق ومراجعة كافة الافتراضات المالية (الإيجار المتوقع، الشغور، النفقات التشغيلية، تكاليف الاستحواذ) بنجاح.") + enrich_note,
                    completed_at=now_dt
                )
                next_task = await WorkflowEngine.spawn_next_workflow_task(
                    conn=conn,
                    current_task=dict(task),
                    outcome=norm_outcome,
                    user_id=user_id,
                    priority="HIGH",
                    parent_task_id=task_id
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"type": "INVEST_FINANCIALS_VALIDATED", "next_task": next_task}
                }
            else:
                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_INVEST_RETURNS_COMPARED",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    task_id=task_id,
                    outcome=outcome,
                    notes=notes or "تم التحفظ على الافتراضات المالية للوحدة المرشحة. تم إعادة توجيه المسار لمقارنة بدائل استثمارية أخرى.",
                    completed_at=now_dt
                )
                next_task = await WorkflowEngine.spawn_next_workflow_task(
                    conn=conn,
                    current_task=dict(task),
                    outcome="REJECTED",
                    user_id=user_id,
                    priority="NORMAL",
                    parent_task_id=task_id
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"type": "INVEST_REMATCH_SPAWNED", "next_task": next_task}
                }

        # 3.5. TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT
        if tmpl_id == "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT":
            norm_outcome = (outcome or "DISCOUNT_ACCEPTED").upper()
            v_data = viewing_data or {}
            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            rep = None
            if task["opportunity_id"]:
                rep = await conn.fetchrow(
                    "SELECT * FROM investment_due_diligence_reports WHERE opportunity_id = $1 ORDER BY created_at DESC LIMIT 1",
                    task["opportunity_id"]
                )

            orig_price = float(rep["purchase_price_sar"] or 0.0) if rep else 0.0
            capex_disc = float(rep["suggested_price_adjustment_sar"] or rep["estimated_capex_sar"] or 0.0) if rep else 0.0

            approved_price = float(v_data.get("approved_acquisition_price") or v_data.get("purchase_price") or 0.0)
            if approved_price <= 0.0:
                if norm_outcome in ("DISCOUNT_ACCEPTED", "ACCEPTED"):
                    approved_price = max(0.0, orig_price - capex_disc) if orig_price > 0 else orig_price
                elif norm_outcome in ("COMPROMISE_AGREED", "OFFER_COMPROMISE"):
                    approved_price = max(0.0, orig_price - (capex_disc / 2.0)) if orig_price > 0 else orig_price
                else:
                    approved_price = orig_price

            equity_cash = float(v_data.get("equity_cash_invested") or v_data.get("cash_invested") or 0.0)
            if equity_cash <= 0.0:
                equity_cash = approved_price

            gross_rent = float(v_data.get("gross_annual_rent") or (float(v_data.get("monthly_rent_forecast") or 0.0) * 12.0))
            if gross_rent <= 0.0 and rep and rep["gross_annual_rent_sar"]:
                gross_rent = float(rep["gross_annual_rent_sar"])
            elif gross_rent <= 0.0 and approved_price > 0:
                gross_rent = approved_price * 0.08

            opex = float(v_data.get("annual_operating_expenses") or v_data.get("operating_expenses_opex") or 0.0)
            if opex <= 0.0 and rep and rep["operating_expenses_opex_sar"]:
                opex = float(rep["operating_expenses_opex_sar"])
            elif opex <= 0.0 and gross_rent > 0:
                opex = gross_rent * 0.10

            target_noi = float(v_data.get("target_net_operating_income_noi") or v_data.get("target_noi") or 0.0)
            if target_noi <= 0.0:
                if rep and rep["net_operating_income_noi_sar"] and float(rep["net_operating_income_noi_sar"]) > 0:
                    target_noi = float(rep["net_operating_income_noi_sar"])
                else:
                    target_noi = max(0.0, gross_rent - (gross_rent * 0.05) - opex)

            cap_rate = round((target_noi / approved_price * 100.0), 2) if approved_price > 0 else 0.0
            coc = round((target_noi / equity_cash * 100.0), 2) if equity_cash > 0 else 0.0
            tot_basis = approved_price + (capex_disc if norm_outcome == "DISCOUNT_REJECTED" else 0.0)
            net_yield = round((target_noi / tot_basis * 100.0), 2) if tot_basis > 0 else 0.0

            if rep:
                await conn.execute(
                    """
                    UPDATE investment_due_diligence_reports
                    SET purchase_price_sar = $1,
                        cash_invested_sar = $2,
                        gross_annual_rent_sar = $3,
                        operating_expenses_opex_sar = $4,
                        net_operating_income_noi_sar = $5,
                        total_investment_basis_sar = $6,
                        cap_rate_percent = $7,
                        net_yield_percent = $8,
                        cash_on_cash_return_percent = $9,
                        updated_at = NOW()
                    WHERE report_id = $10
                    """,
                    approved_price, equity_cash, gross_rent, opex, target_noi,
                    tot_basis, cap_rate, net_yield, coc, rep["report_id"]
                )

            if task["opportunity_id"]:
                await conn.execute(
                    "UPDATE opportunities SET expected_value = $1, updated_at = NOW() WHERE opportunity_id = $2",
                    approved_price, task["opportunity_id"]
                )
                await conn.execute(
                    "UPDATE opportunity_units SET offered_price = $1 WHERE opportunity_id = $2 AND is_primary = TRUE",
                    approved_price, task["opportunity_id"]
                )

            decision_label = (
                "موافقة البائع على الخصم كاملاً" if norm_outcome == "DISCOUNT_ACCEPTED" else
                ("تسوية وتخفيض جزئي متفق عليه" if norm_outcome == "COMPROMISE_AGREED" else "تمسك البائع بالسعر الأصلي")
            )
            act_notes = (
                f"تمت إدارة جولات التفاوض على التعديل السعري وعيوب الفحص ({decision_label}): "
                f"سعر الاستحواذ المعتمد: {approved_price:,.2f} ريال | "
                f"رأس المال النقدي المستثمر (Equity): {equity_cash:,.2f} ريال | "
                f"إجمالي الإيجار السنوي: {gross_rent:,.2f} ريال | "
                f"صافي الدخل المستهدف NOI: {target_noi:,.2f} ريال | "
                f"معدل الرسملة الناتج: {cap_rate}%."
            )
            if notes:
                act_notes = f"{act_notes} {notes}"

            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_INVEST_ACQUISITION_OFFER_PREPARED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome=norm_outcome,
                notes=act_notes,
                completed_at=now_dt
            )

            # Automatically Archive Counter Offer / Price Discount Negotiation Letter
            await WorkflowEngine.archive_workflow_document(
                conn=conn,
                doc_type_code="COUNTER_OFFER_LETTER",
                file_name=f"خطاب_التفاوض_وطلب_تعديل_السعر_CapEx_{task_id}.pdf",
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                unit_id=task.get("unit_id"),
                customer_id=task["customer_id"],
                notes=f"خطاب التفاوض الرسمي لطلب تعديل السعر - الخصم: {capex_disc:,.2f} ريال | السعر المعتمد: {approved_price:,.2f} ريال",
                metadata={
                    "original_price": orig_price,
                    "discount_amount": capex_disc,
                    "revised_price": approved_price,
                    "decision": norm_outcome,
                    "target_noi": target_noi,
                    "cap_rate": cap_rate
                },
                user_id=user_id
            )

            # Check if TASK_INVEST_BASELINE_PERFORMANCE or downstream task already exists
            existing_baseline = None
            if task["opportunity_id"]:
                existing_baseline = await conn.fetchrow(
                    "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_BASELINE_PERFORMANCE' AND status IN ('PENDING', 'OPEN')",
                    task["opportunity_id"]
                )

            next_task = None
            if existing_baseline:
                if existing_baseline["status"] == "PENDING":
                    await conn.execute("UPDATE tasks SET status = 'OPEN' WHERE task_id = $1", existing_baseline["task_id"])
                    existing_baseline = dict(existing_baseline)
                    existing_baseline["status"] = "OPEN"
                next_task = dict(existing_baseline)
            else:
                next_task = await WorkflowEngine.spawn_next_workflow_task(
                    conn=conn,
                    current_task=dict(task),
                    outcome=norm_outcome,
                    user_id=user_id,
                    priority=dict(task).get("priority") or "HIGH",
                    parent_task_id=task_id
                )

            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {
                    "type": "INVEST_DISCOUNT_NEGOTIATED",
                    "approved_acquisition_price": approved_price,
                    "equity_cash_invested": equity_cash,
                    "gross_annual_rent": gross_rent,
                    "target_noi": target_noi,
                    "cap_rate": cap_rate,
                    "next_task": next_task
                }
            }

        # 4. TASK_INVEST_PREPARE_ACQUISITION_OFFER
        if tmpl_id == "TASK_INVEST_PREPARE_ACQUISITION_OFFER":
            norm_outcome = (outcome or "OFFER_ACCEPTED").upper()
            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            if norm_outcome in ("OFFER_ACCEPTED", "OFFER_COMPROMISE", "ACCEPTED", "WON", "COMPLETED"):
                if task["opportunity_id"]:
                    await conn.execute("UPDATE opportunities SET stage = 'WON', updated_at = NOW() WHERE opportunity_id = $1", task["opportunity_id"])
                if lead_id:
                    await conn.execute("UPDATE leads SET status = 'WON', updated_at = NOW() WHERE lead_id = $1", lead_id)

                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_INVEST_ACQUISITION_OFFER_PREPARED",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    task_id=task_id,
                    outcome="OFFER_ACCEPTED",
                    notes=notes or "تم قبول عرض الاستحواذ بنجاح وترقية المعاملة لحالة الإتمام (WON).",
                    completed_at=now_dt
                )

                # Resolve unit_id for investment acquisition
                unit_id = task.get("unit_id")
                if not unit_id and task.get("opportunity_id"):
                    unit_id = await conn.fetchval(
                        "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                        task["opportunity_id"]
                    )
                if not unit_id and lead_id:
                    unit_id = await conn.fetchval(
                        "SELECT unit_id FROM lead_units WHERE lead_id = $1 ORDER BY is_primary DESC LIMIT 1",
                        lead_id
                    )
                if not unit_id and lead_id:
                    unit_id = await conn.fetchval("SELECT unit_id FROM leads WHERE lead_id = $1", lead_id)

                opp_v = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", task["opportunity_id"]) if task["opportunity_id"] else 0.0
                curr_u = await conn.fetchrow("SELECT unit_id, unit_number, status, asking_price FROM units WHERE unit_id = $1", unit_id) if unit_id else None
                res_number = None
                deposit_val = 0.0

                if curr_u and task.get("opportunity_id"):
                    existing_res = await conn.fetchrow(
                        "SELECT reservation_id, reservation_number, deposit_amount FROM reservations WHERE opportunity_id = $1 AND unit_id = $2 AND status = 'ACTIVE'",
                        task["opportunity_id"], unit_id
                    )
                    if existing_res:
                        res_number = existing_res["reservation_number"]
                        deposit_val = float(existing_res["deposit_amount"] or 0.0)
                    else:
                        res_id = await get_next_id(conn, "reservations", "res")
                        res_count = await conn.fetchval("SELECT count(*) + 1 FROM reservations")
                        res_number = f"RES-INV-{res_count:05d}"
                        deposit_val = round(float(opp_v or 0.0) * 0.05, 2)
                        if deposit_val <= 0:
                            deposit_val = round(float(curr_u["asking_price"] or 100000.0) * 0.05, 2)
                        expires_at = now_dt + timedelta(days=14)

                        if task.get("customer_id"):
                            await conn.execute(
                                """
                                INSERT INTO reservations (
                                    reservation_id, opportunity_id, unit_id, customer_id,
                                    reservation_number, reserved_at, expires_at, deposit_amount, status
                                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'ACTIVE')
                                """,
                                res_id, task["opportunity_id"], unit_id, task["customer_id"],
                                res_number, now_dt, expires_at, deposit_val
                            )

                    # Atomically update unit status to RESERVED and record audit log in unit_status_history
                    if curr_u["status"] != "RESERVED" and curr_u["status"] != "SOLD":
                        await conn.execute("UPDATE units SET status = 'RESERVED', updated_at = NOW() WHERE unit_id = $1", unit_id)
                        hist_id = await get_next_id(conn, "unit_status_history", "ush")
                        await conn.execute(
                            """
                            INSERT INTO unit_status_history (
                                unit_status_history_id, unit_id, old_status, new_status,
                                changed_by_user_id, changed_at, reason
                            ) VALUES ($1, $2, $3, 'RESERVED', $4, NOW(), $5)
                            """,
                            hist_id, unit_id, curr_u["status"], user_id,
                            f"حجز الأصل الاستثماري بموجب قبول عرض الاستحواذ وسند العربون ({res_number})"
                        )

                    # Archive Reservation & Earnest Money Document
                    if res_number:
                        cust_row = await conn.fetchrow("SELECT first_name, last_name, company_name, mobile FROM customers WHERE customer_id = $1", task["customer_id"]) if task.get("customer_id") else None
                        cust_full_name = f"{cust_row['first_name'] or ''} {cust_row['last_name'] or ''}".strip() or (cust_row['company_name'] if cust_row else 'المستثمر')
                        await WorkflowEngine.archive_workflow_document(
                            conn=conn,
                            doc_type_code="RESERVATION",
                            file_name=f"سند_حجز_أصل_استثماري_{res_number}.pdf",
                            lead_id=lead_id,
                            opportunity_id=task["opportunity_id"],
                            task_id=task_id,
                            unit_id=unit_id,
                            customer_id=task["customer_id"],
                            notes=f"سند حجز أصل استثماري وإيداع عربون بموجب قبول عرض الاستحواذ رقم {res_number} بمبلغ عربون {deposit_val:,.2f} ريال",
                            metadata={
                                "reservation_number": res_number,
                                "deposit_amount": deposit_val,
                                "offer_amount": float(opp_v or 0.0),
                                "unit_number": curr_u["unit_number"],
                                "customer_name": cust_full_name,
                                "expires_at": (now_dt + timedelta(days=14)).isoformat(),
                                "status": "ACTIVE"
                            },
                            user_id=user_id
                        )

                # Automatically Archive Commercial Acquisition Offer
                await WorkflowEngine.archive_workflow_document(
                    conn=conn,
                    doc_type_code="COMMERCIAL_OFFER",
                    file_name=f"عرض_الاستحواذ_المالي_الرسمي_{task_id}.pdf",
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    task_id=task_id,
                    unit_id=unit_id or task.get("unit_id"),
                    customer_id=task["customer_id"],
                    notes=f"عرض الاستحواذ المالي الرسمي المعتمد بمبلغ {float(opp_v or 0.0):,.2f} ريال",
                    metadata={
                        "offer_amount": float(opp_v or 0.0),
                        "earnest_money": float(opp_v or 0.0) * 0.05,
                        "unit_number": curr_u["unit_number"] if curr_u else None
                    },
                    user_id=user_id
                )
                next_task = await WorkflowEngine.spawn_next_workflow_task(
                    conn=conn,
                    current_task=dict(task),
                    outcome=norm_outcome,
                    user_id=user_id,
                    priority="HIGH",
                    parent_task_id=task_id
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {
                        "type": "INVEST_ACQUISITION_WON",
                        "unit_id": unit_id,
                        "unit_status": "RESERVED" if curr_u else None,
                        "reservation_number": res_number,
                        "deposit_amount": deposit_val,
                        "next_task": next_task
                    }
                }
            else:
                # Release unit if previously reserved
                rel_unit_id = task.get("unit_id")
                if not rel_unit_id and task.get("opportunity_id"):
                    rel_unit_id = await conn.fetchval(
                        "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                        task["opportunity_id"]
                    )
                if rel_unit_id:
                    if task.get("opportunity_id"):
                        await conn.execute(
                            "UPDATE reservations SET status = 'CANCELLED' WHERE opportunity_id = $1 AND unit_id = $2 AND status = 'ACTIVE'",
                            task["opportunity_id"], rel_unit_id
                        )
                    curr_st = await conn.fetchval("SELECT status FROM units WHERE unit_id = $1", rel_unit_id)
                    if curr_st == "RESERVED":
                        await conn.execute("UPDATE units SET status = 'AVAILABLE', updated_at = NOW() WHERE unit_id = $1", rel_unit_id)
                        hist_id = await get_next_id(conn, "unit_status_history", "ush")
                        await conn.execute(
                            """
                            INSERT INTO unit_status_history (
                                unit_status_history_id, unit_id, old_status, new_status,
                                changed_by_user_id, changed_at, reason
                            ) VALUES ($1, $2, 'RESERVED', 'AVAILABLE', $3, NOW(), $4)
                            """,
                            hist_id, rel_unit_id, user_id,
                            "إلغاء حجز الأصل الاستثماري وإعادته للمخزون المتاح إثر عدم قبول عرض الاستحواذ"
                        )

                activity = await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_INVEST_RETURNS_COMPARED",
                    user_id=user_id,
                    customer_id=task["customer_id"],
                    lead_id=lead_id,
                    opportunity_id=task["opportunity_id"],
                    task_id=task_id,
                    outcome=outcome,
                    notes=notes or "تم رفض أو عدم إتمام عرض الاستحواذ الحالي. تم فتح مسار المقارنة لاختيار وحدة بديلة للعميل.",
                    completed_at=now_dt
                )
                next_task = await WorkflowEngine.spawn_next_workflow_task(
                    conn=conn,
                    current_task=dict(task),
                    outcome="OFFER_REJECTED",
                    user_id=user_id,
                    priority="NORMAL",
                    parent_task_id=task_id
                )
                return {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "completed_at": now_dt.isoformat(),
                    "activity": activity,
                    "business_transition": {"type": "INVEST_REMATCH_SPAWNED", "next_task": next_task}
                }

        # 5. TASK_INVEST_BASELINE_PERFORMANCE
        if tmpl_id == "TASK_INVEST_BASELINE_PERFORMANCE":
            v_data = viewing_data or {}

            rep_row = None
            if task["opportunity_id"]:
                rep_row = await conn.fetchrow(
                    """
                    SELECT * FROM investment_due_diligence_reports 
                    WHERE opportunity_id = $1 
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    task["opportunity_id"]
                )

            p_price = float(v_data.get("purchase_price") or (float(rep_row["purchase_price_sar"]) if rep_row and rep_row["purchase_price_sar"] else 0.0))
            m_rent = float(v_data.get("monthly_rent_forecast") or (float(rep_row["gross_annual_rent_sar"]) / 12.0 if rep_row and rep_row["gross_annual_rent_sar"] else 0.0))
            opex = float(v_data.get("annual_operating_expenses") or (float(rep_row["operating_expenses_opex_sar"]) if rep_row and rep_row["operating_expenses_opex_sar"] else 0.0))
            vac = float(v_data.get("annual_vacancy_allowance") or (float(rep_row["vacancy_allowance_sar"]) if rep_row and rep_row["vacancy_allowance_sar"] else 0.0))
            capex = float(rep_row["estimated_capex_sar"] if rep_row and rep_row["estimated_capex_sar"] else 0.0)
            cash_inv = float(v_data.get("cash_invested") or (float(rep_row["cash_invested_sar"]) if rep_row and rep_row["cash_invested_sar"] and rep_row["cash_invested_sar"] > 0 else (p_price if p_price > 0 else 1.0)))

            if task["opportunity_id"] and p_price == 0.0:
                opp_v = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", task["opportunity_id"])
                p_price = float(opp_v or 0.0)
                if cash_inv <= 1.0 and p_price > 0:
                    cash_inv = p_price
                if m_rent == 0.0 and p_price > 0:
                    m_rent = p_price * 0.08 / 12.0

            from app.services.calculation_service import CalculationService
            r_metrics = CalculationService.calculate_rental_metrics(
                monthly_rent=m_rent,
                purchase_price=p_price,
                annual_vacancy_allowance=vac,
                annual_operating_expenses=opex,
                acquisition_costs=capex
            )
            i_returns = CalculationService.calculate_investment_returns(
                purchase_price=p_price,
                cash_invested=cash_inv,
                annual_pre_tax_cash_flow=r_metrics["net_operating_income"]
            )

            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            dd_ref = f" استناداً إلى تقرير الفحص النافي للجهالة (#{rep_row['report_id']})" if rep_row else ""
            base_notes = notes or (
                f"تم تأسيس وتوثيق خط الأساس الاستثماري{dd_ref}: تكلفة الاستحواذ: {p_price:,.2f} ريال | "
                f"CapEx معتمد: {capex:,.2f} ريال | إجمالي التكلفة: {r_metrics['total_investment_basis']:,.2f} ريال | "
                f"صافي الدخل التشغيلي المستهدف (NOI): {r_metrics['net_operating_income']:,.2f} ريال سنوياً | "
                f"معدل الرسملة (Cap Rate): {round((r_metrics['net_operating_income'] / p_price * 100.0), 2) if p_price > 0 else 0.0}% | "
                f"معدل العائد الصافي المستهدف (Net Yield): {r_metrics['net_operating_yield_percent']}% | "
                f"العائد على النقد المستثمر (CoC): {i_returns['cash_on_cash_return_percent']}%."
            )
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_INVEST_BASELINE_ESTABLISHED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome="BASELINE_ESTABLISHED",
                notes=base_notes,
                completed_at=now_dt
            )

            # Resolve unit_id for final investment conveyance and deed transfer
            unit_id = task.get("unit_id")
            if not unit_id and task.get("opportunity_id"):
                unit_id = await conn.fetchval(
                    "SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1 ORDER BY is_primary DESC LIMIT 1",
                    task["opportunity_id"]
                )
            if not unit_id and rep_row and rep_row.get("unit_id"):
                unit_id = rep_row["unit_id"]
            if not unit_id and lead_id:
                unit_id = await conn.fetchval(
                    "SELECT unit_id FROM lead_units WHERE lead_id = $1 ORDER BY is_primary DESC LIMIT 1",
                    lead_id
                )
            if not unit_id and lead_id:
                unit_id = await conn.fetchval("SELECT unit_id FROM leads WHERE lead_id = $1", lead_id)

            curr_u = await conn.fetchrow("SELECT unit_id, unit_number, status, owner_customer_id FROM units WHERE unit_id = $1", unit_id) if unit_id else None
            if curr_u and curr_u["status"] != "SOLD":
                await conn.execute(
                    "UPDATE units SET status = 'SOLD', owner_customer_id = COALESCE($1, owner_customer_id), updated_at = NOW() WHERE unit_id = $2",
                    task.get("customer_id"), unit_id
                )
                hist_id = await get_next_id(conn, "unit_status_history", "ush")
                await conn.execute(
                    """
                    INSERT INTO unit_status_history (
                        unit_status_history_id, unit_id, old_status, new_status,
                        changed_by_user_id, changed_at, reason
                    ) VALUES ($1, $2, $3, 'SOLD', $4, NOW(), $5)
                    """,
                    hist_id, unit_id, curr_u["status"], user_id,
                    f"اكتمال صفقة الاستحواذ العقاري وتأسيس خط الأساس للأصل ونقل ملكية الوحدة {curr_u['unit_number']} للمستثمر"
                )

            # Convert reservation status to CONVERTED
            if task.get("opportunity_id"):
                await conn.execute(
                    "UPDATE reservations SET status = 'CONVERTED' WHERE opportunity_id = $1 AND status = 'ACTIVE'",
                    task["opportunity_id"]
                )

            # Automatically Archive Investment Baseline Financial Performance Sheet
            cap_rate_val = round((r_metrics['net_operating_income'] / p_price * 100.0), 2) if p_price > 0 else 0.0
            await WorkflowEngine.archive_workflow_document(
                conn=conn,
                doc_type_code="BASELINE_FINANCIAL_SHEET",
                file_name=f"ورقة_خط_الأساس_المالي_والاستثماري_{task_id}.pdf",
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                unit_id=unit_id or task.get("unit_id"),
                customer_id=task["customer_id"],
                notes=f"ورقة خط الأساس المالي والأداء الاستثماري - صافي الدخل المستهدف NOI: {r_metrics.get('net_operating_income', 0.0):,.2f} ريال",
                metadata={
                    "acquisition_price": p_price,
                    "equity": cash_inv,
                    "gross_annual_rent": r_metrics.get("gross_annual_rent"),
                    "target_noi": r_metrics.get("net_operating_income"),
                    "cap_rate": cap_rate_val,
                    "coc_return": i_returns.get("cash_on_cash_return_percent"),
                    "unit_number": curr_u["unit_number"] if curr_u else None
                },
                user_id=user_id
            )

            next_task = await WorkflowEngine.spawn_next_workflow_task(
                conn=conn,
                current_task=dict(task),
                outcome="BASELINE_ESTABLISHED",
                user_id=user_id,
                priority="NORMAL",
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {
                    "type": "INVEST_BASELINE_ESTABLISHED",
                    "unit_id": unit_id,
                    "unit_status": "SOLD" if curr_u else None,
                    "baseline_metrics": r_metrics,
                    "returns": i_returns,
                    "next_task": next_task
                }
            }

        # 6. TASK_INVEST_MONITOR_ACTUAL_RETURNS
        if tmpl_id == "TASK_INVEST_MONITOR_ACTUAL_RETURNS":
            v_data = viewing_data or {}

            rep_row = None
            if task["opportunity_id"]:
                rep_row = await conn.fetchrow(
                    """
                    SELECT * FROM investment_due_diligence_reports 
                    WHERE opportunity_id = $1 
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    task["opportunity_id"]
                )

            act_inc = float(v_data.get("actual_rental_income") or 0.0)
            act_exp = float(v_data.get("actual_expenses") or 0.0)
            forecast_inc = float(v_data.get("monthly_rent_forecast") or 0.0) * 12.0
            if forecast_inc == 0.0 and rep_row and rep_row["gross_annual_rent_sar"]:
                forecast_inc = float(rep_row["gross_annual_rent_sar"])

            if forecast_inc == 0.0 and task["opportunity_id"]:
                opp_v = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", task["opportunity_id"])
                if opp_v and float(opp_v) > 0:
                    forecast_inc = float(opp_v) * 0.08
            if act_inc == 0.0 and forecast_inc > 0:
                act_inc = forecast_inc

            from app.services.calculation_service import CalculationService
            var_data = CalculationService.calculate_forecast_rental_variance(
                actual_income=act_inc,
                forecast_income=forecast_inc
            )

            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            dd_info = f" (مقارنة بخط أساس الفحص النافي للجهالة #{rep_row['report_id']})" if rep_row else ""
            mon_notes = notes or (
                f"تمت مراجعة العوائد الفعلية ومقارنتها بخط الأساس{dd_info}: "
                f"الدخل الفعلي المحصل: {act_inc:,.2f} ريال | الدخل المستهدف بالخطة: {forecast_inc:,.2f} ريال | "
                f"المصروفات الفعلية: {act_exp:,.2f} ريال | "
                f"انحراف الأداء عن التوقعات: {var_data['variance_percent'] if var_data['variance_percent'] is not None else 0.0}%."
            )
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_INVEST_RETURNS_MONITORED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome=outcome or "MONITORED",
                notes=mon_notes,
                completed_at=now_dt
            )

            next_task = await WorkflowEngine.spawn_next_workflow_task(
                conn=conn,
                current_task=dict(task),
                outcome=outcome or "MONITORED",
                user_id=user_id,
                priority="NORMAL",
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {
                    "type": "INVEST_RETURNS_MONITORED",
                    "variance": var_data,
                    "next_task": next_task
                }
            }

        # 7. TASK_INVEST_PORTFOLIO_REVIEW
        if tmpl_id == "TASK_INVEST_PORTFOLIO_REVIEW":
            rep_row = None
            if task["opportunity_id"]:
                rep_row = await conn.fetchrow(
                    """
                    SELECT * FROM investment_due_diligence_reports 
                    WHERE opportunity_id = $1 
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    task["opportunity_id"]
                )

            rec_outcome = (outcome or "HOLD").upper()
            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            dd_info = f" (مقارنة بمستهدف خط الأساس: عائد {float(rep_row['net_yield_percent'])}% و NOI {float(rep_row['net_operating_income_noi_sar']):,.2f} ريال)" if rep_row and rep_row['net_operating_income_noi_sar'] else ""
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_INVEST_PORTFOLIO_REVIEWED",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                opportunity_id=task["opportunity_id"],
                task_id=task_id,
                outcome=rec_outcome,
                notes=notes or f"تم إنجاز المراجعة الدورية للمحفظة الاستثمارية{dd_info}. التوصية الاستراتيجية المعتمدة: ({rec_outcome}).",
                completed_at=now_dt
            )

            next_task = await WorkflowEngine.spawn_next_workflow_task(
                conn=conn,
                current_task=dict(task),
                outcome=rec_outcome,
                user_id=user_id,
                priority="NORMAL",
                parent_task_id=task_id
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {
                    "type": "INVEST_PORTFOLIO_REVIEWED",
                    "recommendation": rec_outcome,
                    "next_task": next_task
                }
            }

        # Stage Lead Assignment Handling: TASK_LEAD_ASSIGN
        if tmpl_id == "TASK_LEAD_ASSIGN" and lead_id:
            v_data = viewing_data or {}
            target_agent_id = v_data.get("assigned_user_id") or task.get("assigned_user_id")
            target_branch_id = v_data.get("branch_id")
            if not target_agent_id:
                raise ValueError("يجب تحديد الوسيط المراد تعيين الطلب إليه لإنجاز المهمة.")

            await conn.execute("UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2", now_dt, task_id)

            assign_res = await WorkflowEngine.on_lead_assigned(
                conn=conn,
                lead_id=lead_id,
                assigned_user_id=target_agent_id,
                assigner_user_id=user_id,
                branch_id=target_branch_id,
                notes=notes
            )

            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": assign_res.get("activity"),
                "business_transition": {
                    "type": "LEAD_ASSIGNED",
                    "assigned_user_id": target_agent_id,
                    "branch_id": target_branch_id,
                    "assignment_details": assign_res
                }
            }

        # 4. Stage A Handling: TASK_LEAD_COMPLETE_INFO
        if tmpl_id == "TASK_LEAD_COMPLETE_INFO" and lead_id:
            q_data = qualification_data or {}
            lead_updates = []
            lead_params = []
            p_i = 1
            if q_data.get("budget_min") is not None:
                lead_updates.append(f"budget_min = ${p_i}")
                lead_params.append(q_data["budget_min"])
                p_i += 1
            if q_data.get("budget_max") is not None:
                lead_updates.append(f"budget_max = ${p_i}")
                lead_params.append(q_data["budget_max"])
                p_i += 1
            if q_data.get("preferred_city_id") is not None:
                lead_updates.append(f"preferred_city_id = ${p_i}")
                lead_params.append(q_data["preferred_city_id"])
                p_i += 1
            if q_data.get("preferred_property_type_id") is not None:
                lead_updates.append(f"preferred_property_type_id = ${p_i}")
                lead_params.append(q_data["preferred_property_type_id"])
                p_i += 1
            if lead_updates:
                lead_params.append(lead_id)
                await conn.execute(f"UPDATE leads SET {', '.join(lead_updates)}, updated_at = NOW() WHERE lead_id = ${p_i}", *lead_params)
            
            activity = await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_LEAD_FOLLOWUP",
                user_id=user_id,
                customer_id=task["customer_id"],
                lead_id=lead_id,
                task_id=task_id,
                outcome="INFO_COMPLETED",
                notes=notes or "تم استكمال وتحديث بيانات الطلب بنجاح.",
                completed_at=now_dt
            )
            return {
                "task_id": task_id,
                "status": "COMPLETED",
                "completed_at": now_dt.isoformat(),
                "activity": activity,
                "business_transition": {"lead_id": lead_id, "status": "INFO_COMPLETED"}
            }

        # 5. Determine and record corresponding Activity for other tasks
        act_template_id = "ACT_LEAD_FIRST_CONTACT"
        if tmpl_id in ("TASK_LEAD_FIRST_CONTACT", "TASK_RENT_LEAD_FIRST_CONTACT", "TASK_INVEST_LEAD_FIRST_CONTACT"):
            act_template_id = "ACT_LEAD_FIRST_CONTACT"
        elif tmpl_id == "TASK_LEAD_FOLLOWUP":
            act_template_id = "ACT_LEAD_FOLLOWUP"
        elif tmpl_id == "TASK_LEAD_QUALIFY":
            act_template_id = "ACT_LEAD_QUALIFIED"
        elif tmpl_id == "TASK_LEAD_ASSIGN":
            act_template_id = "ACT_LEAD_ASSIGNED"
        elif tmpl_id == "TASK_RENT_MATCH_PROPERTIES":
            act_template_id = "ACT_RENT_PROPERTIES_MATCHED"
        elif tmpl_id == "TASK_RENT_VIEWING_FOLLOW_UP":
            act_template_id = "ACT_VIEWING_REPORT_SUBMITTED"
        elif tmpl_id == "TASK_RENT_PREPARE_TENANCY":
            act_template_id = "ACT_TENANCY_ACTIVATED"
        elif tmpl_id == "TASK_RENT_COLLECTION_MONITORING":
            act_template_id = "ACT_RENT_PAYMENT_COLLECTED"
        elif tmpl_id == "TASK_INVEST_CONFIRM_OBJECTIVES":
            act_template_id = "ACT_INVEST_OBJECTIVES_CONFIRMED"
        elif tmpl_id == "TASK_INVEST_COMPARE_RETURNS":
            act_template_id = "ACT_INVEST_RETURNS_COMPARED"
        elif tmpl_id == "TASK_INVEST_SCHEDULE_INSPECTION":
            act_template_id = "ACT_INVEST_INSPECTION_SCHEDULED"
        elif tmpl_id == "TASK_INVEST_INSPECTION_REPORT":
            act_template_id = "ACT_INVEST_INSPECTION_COMPLETED"
        elif tmpl_id == "TASK_INVEST_VALIDATE_FINANCIALS":
            act_template_id = "ACT_INVEST_FINANCIALS_VALIDATED"
        elif tmpl_id == "TASK_INVEST_PREPARE_ACQUISITION_OFFER":
            act_template_id = "ACT_INVEST_ACQUISITION_OFFER_PREPARED"
        elif tmpl_id == "TASK_INVEST_BASELINE_PERFORMANCE":
            act_template_id = "ACT_INVEST_BASELINE_ESTABLISHED"
        elif tmpl_id == "TASK_INVEST_MONITOR_ACTUAL_RETURNS":
            act_template_id = "ACT_INVEST_RETURNS_MONITORED"
        elif tmpl_id == "TASK_INVEST_PORTFOLIO_REVIEW":
            act_template_id = "ACT_INVEST_PORTFOLIO_REVIEWED"

        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id=act_template_id,
            user_id=user_id,
            customer_id=task["customer_id"],
            lead_id=task["lead_id"],
            opportunity_id=task["opportunity_id"],
            task_id=task_id,
            outcome=outcome,
            notes=notes,
            completed_at=now_dt
        )

        # 6. Event-Driven Business Status Transitions for First Contact & Follow-up
        business_transition = None

        if lead_id and tmpl_id in ("TASK_LEAD_FIRST_CONTACT", "TASK_RENT_LEAD_FIRST_CONTACT", "TASK_INVEST_LEAD_FIRST_CONTACT", "TASK_LEAD_FOLLOWUP"):
            lead = await conn.fetchrow("SELECT status, assigned_user_id, inquiry_type FROM leads WHERE lead_id = $1", lead_id)
            if lead:
                if outcome in ("QUALIFIED", "CONVERTED"):
                    q_data = qualification_data or {}
                    qual_res = await WorkflowEngine.on_lead_qualified(
                        conn=conn,
                        lead_id=lead_id,
                        user_id=user_id,
                        budget_min=q_data.get("budget_min"),
                        budget_max=q_data.get("budget_max"),
                        preferred_property_type_id=q_data.get("preferred_property_type_id"),
                        preferred_city_id=q_data.get("preferred_city_id"),
                        notes=notes,
                        parent_task_id=task_id
                    )
                    return {
                        "task_id": task_id,
                        "status": "COMPLETED",
                        "completed_at": now_dt.isoformat(),
                        "activity": qual_res["activity"],
                        "business_transition": qual_res
                    }
                elif outcome == "CONNECTED":
                    # Crucial Rule: ONLY marked CONTACTED when actual connection is recorded!
                    await conn.execute(
                        """
                        UPDATE leads
                        SET status = 'CONTACTED', first_contact_at = COALESCE(first_contact_at, $1), updated_at = NOW()
                        WHERE lead_id = $2
                        """,
                        now_dt, lead_id
                    )
                    business_transition = {"lead_id": lead_id, "new_status": "CONTACTED"}

                    # Automatically spawn qualification task
                    qual_task, _ = await WorkflowEngine.spawn_task_from_template(
                        conn=conn,
                        template_id="TASK_LEAD_QUALIFY",
                        lead_id=lead_id,
                        customer_id=task["customer_id"],
                        assigned_user_id=lead["assigned_user_id"] or user_id,
                        priority="HIGH",
                        parent_task_id=task_id
                    )
                    business_transition["qualification_task"] = qual_task

                elif outcome in ("NO_ANSWER", "BUSY", "UNREACHABLE"):
                    curr_retries = int(task["retry_count"]) if "retry_count" in task and task["retry_count"] is not None else 0
                    next_retries = curr_retries + 1

                    if next_retries < 3:
                        # Schedule follow-up retry in 3 hours
                        followup_due = now_dt + timedelta(hours=3)
                        followup_task, _ = await WorkflowEngine.spawn_task_from_template(
                            conn=conn,
                            template_id="TASK_LEAD_FOLLOWUP",
                            lead_id=lead_id,
                            customer_id=task["customer_id"],
                            assigned_user_id=lead["assigned_user_id"] or user_id,
                            custom_due_at=followup_due,
                            priority="NORMAL",
                            parent_task_id=task_id
                        )
                        if followup_task:
                            await conn.execute("UPDATE tasks SET retry_count = $1 WHERE task_id = $2", next_retries, followup_task["task_id"])
                            followup_task["retry_count"] = next_retries

                        business_transition = {
                            "lead_id": lead_id,
                            "status": lead["status"],
                            "retry_count": next_retries,
                            "scheduled_followup": followup_due.isoformat(),
                            "followup_task": followup_task
                        }
                    else:
                        # Max-3 Retries reached: Terminal transition to UNREACHABLE per research policy
                        await conn.execute(
                            """
                            UPDATE leads
                            SET status = 'UNREACHABLE', updated_at = NOW()
                            WHERE lead_id = $1
                            """,
                            lead_id
                        )
                        business_transition = {
                            "lead_id": lead_id,
                            "new_status": "UNREACHABLE",
                            "retry_count": next_retries,
                            "max_retries_exceeded": True
                        }

                elif outcome == "CALLBACK_REQUESTED":
                    v_data = viewing_data or {}
                    cb_time = v_data.get("callback_at")
                    if isinstance(cb_time, str):
                        cb_dt = datetime.fromisoformat(cb_time.replace("Z", "+00:00"))
                    elif isinstance(cb_time, datetime):
                        cb_dt = cb_time
                    else:
                        cb_dt = now_dt + timedelta(hours=24)

                    followup_task, _ = await WorkflowEngine.spawn_task_from_template(
                        conn=conn,
                        template_id="TASK_LEAD_FOLLOWUP",
                        lead_id=lead_id,
                        customer_id=task["customer_id"],
                        assigned_user_id=lead["assigned_user_id"] or user_id,
                        custom_due_at=cb_dt,
                        priority="HIGH",
                        parent_task_id=task_id
                    )
                    business_transition = {
                        "lead_id": lead_id,
                        "status": lead["status"],
                        "callback_scheduled_at": cb_dt.isoformat(),
                        "followup_task": followup_task
                    }

                elif outcome == "INVALID_CONTACT":
                    await conn.execute(
                        """
                        UPDATE leads
                        SET status = 'DISQUALIFIED', first_contact_at = COALESCE(first_contact_at, $1), updated_at = NOW()
                        WHERE lead_id = $2
                        """,
                        now_dt, lead_id
                    )
                    business_transition = {"lead_id": lead_id, "new_status": "DISQUALIFIED", "reason": "INVALID_CONTACT"}

                elif outcome in ("NOT_INTERESTED", "DISQUALIFIED"):
                    await conn.execute(
                        """
                        UPDATE leads
                        SET status = 'DISQUALIFIED', first_contact_at = COALESCE(first_contact_at, $1), updated_at = NOW()
                        WHERE lead_id = $2
                        """,
                        now_dt, lead_id
                    )
                    business_transition = {"lead_id": lead_id, "new_status": "DISQUALIFIED"}

        # Fallback Dynamic Database Progression for any tasks without hardcoded custom returns:
        # (Ad-hoc tasks with successors, intermediate pipeline steps, etc.)
        # Excludes tasks that have already completed their lifecycle routing (e.g. Lead First Contact/Followup with terminal outcome)
        is_first_contact_or_followup = tmpl_id in (
            "TASK_LEAD_FIRST_CONTACT", "TASK_RENT_LEAD_FIRST_CONTACT",
            "TASK_INVEST_LEAD_FIRST_CONTACT", "TASK_LEAD_FOLLOWUP"
        )
        is_terminal_transition = bool(business_transition and (
            business_transition.get("max_retries_exceeded") or 
            business_transition.get("new_status") in ("DISQUALIFIED", "UNREACHABLE", "LOST")
        ))

        if not is_first_contact_or_followup and not is_terminal_transition:
            if not business_transition or ("next_task" not in business_transition and "qualification_task" not in business_transition and "followup_task" not in business_transition):
                db_next = await WorkflowEngine.spawn_next_workflow_task(
                    conn=conn,
                    current_task=dict(task),
                    outcome=outcome,
                    user_id=user_id,
                    priority="NORMAL",
                    parent_task_id=task_id
                )
                if db_next:
                    if business_transition is None:
                        business_transition = {}
                    business_transition["next_task"] = db_next

        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "completed_at": now_dt.isoformat(),
            "activity": activity,
            "business_transition": business_transition
        }

    @staticmethod
    async def reopen_task(
        conn: asyncpg.Connection,
        task_id: str,
        user_id: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Smart Reopen & Undo Engine
        ==========================
        Reverts an erroneously completed task back to PENDING and cascades safe rollbacks:
        1. Checks that the task is currently COMPLETED.
        2. Detects all downstream tasks (by parent_task_id or timeline matching).
        3. SAFETY BLOCK: If any downstream task has status == 'COMPLETED', halts and raises
           an error preventing corrupting subsequent real work.
        4. If safe:
           - Deletes or cancels the untouched downstream tasks.
           - Reverts Lead / Opportunity lifecycle stages to prior state.
           - Reverts or cancels scheduled Viewings.
           - Cleans up completion activity records.
           - Resets the original task status = 'PENDING', completed_at = NULL.
           - Logs an immutable ACT_TASK_REOPENED audit activity.
        """
        now_dt = datetime.now(timezone.utc)
        task = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
        if not task:
            raise ValueError(f"المهمة '{task_id}' غير موجودة (Task not found).")
        if task["status"] != "COMPLETED":
            raise ValueError(f"المهمة ليست مكتملة حالياً (الحالة الحالية: {task['status']}). يمكن إعادة فتح المهام المكتملة فقط.")

        tmpl_id = task["template_id"]
        lead_id = task["lead_id"]
        opp_id = task["opportunity_id"]
        cust_id = task["customer_id"]
        completed_at = task["completed_at"] or now_dt
        cutoff_dt = completed_at - timedelta(seconds=30)

        # 1. Identify Downstream / Child Tasks
        # Query tasks linked explicitly by parent_task_id OR created for this entity after/at completed_at
        downstream_rows = await conn.fetch(
            """
            SELECT task_id, template_id, title, status, created_at, assigned_user_id
            FROM tasks
            WHERE task_id != $1
              AND (
                  parent_task_id = $1
                  OR (
                      created_at >= $2
                      AND (
                          ($3::text IS NOT NULL AND lead_id = $3) OR
                          ($4::text IS NOT NULL AND opportunity_id = $4)
                      )
                  )
              )
            ORDER BY created_at ASC
            """,
            task_id, cutoff_dt, lead_id, opp_id
        )

        downstream_tasks = [dict(r) for r in downstream_rows]

        # 2. Safety Block Check: Has any downstream task been completed?
        for dt in downstream_tasks:
            if dt["status"] == "COMPLETED":
                raise ValueError(
                    f"لا يمكن التراجع تلقائياً لوجود مهمة تابعة ({dt['title']} - #{dt['task_id']}) تم إنجازها بالفعل! يجب التراجع عن المهمة اللاحقة أولاً."
                )

        # 3. Clean up untouched downstream tasks
        cancelled_downstream = []
        for dt in downstream_tasks:
            # Check if activities exist for this downstream task
            act_count = await conn.fetchval(
                "SELECT count(*) FROM activities WHERE task_id = $1", dt["task_id"]
            )
            if not act_count or act_count == 0:
                await conn.execute("DELETE FROM tasks WHERE task_id = $1", dt["task_id"])
            else:
                await conn.execute("UPDATE tasks SET status = 'CANCELLED' WHERE task_id = $1", dt["task_id"])
            cancelled_downstream.append({"task_id": dt["task_id"], "title": dt["title"]})

        # 4. Entity State Reversions
        lead_reverted = None
        opp_reverted = None
        viewing_reverted = None

        # A) First Contact & Follow-up reversions
        if tmpl_id in ("TASK_LEAD_FIRST_CONTACT", "TASK_RENT_LEAD_FIRST_CONTACT", "TASK_INVEST_LEAD_FIRST_CONTACT", "TASK_LEAD_FOLLOWUP") and lead_id:
            lead = await conn.fetchrow("SELECT status, assigned_user_id FROM leads WHERE lead_id = $1", lead_id)
            if lead and lead["status"] in ("CONTACTED", "UNREACHABLE", "DISQUALIFIED"):
                prev_lead_status = "ASSIGNED" if lead["assigned_user_id"] else "NEW"
                # Check if there are other completed contact tasks for this lead
                other_contact = await conn.fetchval(
                    """
                    SELECT count(*) FROM tasks 
                    WHERE lead_id = $1 AND task_id != $2 
                      AND template_id IN ('TASK_LEAD_FIRST_CONTACT', 'TASK_RENT_LEAD_FIRST_CONTACT', 'TASK_INVEST_LEAD_FIRST_CONTACT', 'TASK_LEAD_FOLLOWUP')
                      AND status = 'COMPLETED'
                    """,
                    lead_id, task_id
                )
                if not other_contact or other_contact == 0:
                    await conn.execute(
                        "UPDATE leads SET status = $1, first_contact_at = NULL, updated_at = NOW() WHERE lead_id = $2",
                        prev_lead_status, lead_id
                    )
                else:
                    await conn.execute(
                        "UPDATE leads SET status = $1, updated_at = NOW() WHERE lead_id = $2",
                        prev_lead_status, lead_id
                    )
                lead_reverted = prev_lead_status

        # B) Lead Qualification reversions
        elif tmpl_id == "TASK_LEAD_QUALIFY" and lead_id:
            lead = await conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            if lead and lead["status"] in ("QUALIFIED", "DISQUALIFIED"):
                await conn.execute(
                    "UPDATE leads SET status = 'CONTACTED', updated_at = NOW() WHERE lead_id = $1",
                    lead_id
                )
                lead_reverted = "CONTACTED"

            # Check linked opportunity
            opp = await conn.fetchrow(
                "SELECT opportunity_id, stage FROM opportunities WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 1",
                lead_id
            )
            if opp and opp["stage"] in ("QUALIFIED", "LOST"):
                # If no other completed tasks or viewings exist on this opportunity, delete or revert it
                opp_acts = await conn.fetchval(
                    "SELECT count(*) FROM activities WHERE opportunity_id = $1 AND template_id NOT IN ('ACT_LEAD_QUALIFIED', 'ACT_RENT_LEAD_QUALIFIED', 'ACT_INVEST_LEAD_QUALIFIED')",
                    opp["opportunity_id"]
                )
                if not opp_acts or opp_acts == 0:
                    await conn.execute("UPDATE activities SET opportunity_id = NULL WHERE opportunity_id = $1", opp["opportunity_id"])
                    await conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp["opportunity_id"])
                    await conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp["opportunity_id"])
                    opp_reverted = "DELETED"
                else:
                    await conn.execute("UPDATE opportunities SET stage = 'QUALIFIED', updated_at = NOW() WHERE opportunity_id = $1", opp["opportunity_id"])
                    opp_reverted = "QUALIFIED"

        # C) Property Matching & Investment Evaluation reversions
        elif tmpl_id in ("TASK_OPPORTUNITY_MATCH_PROPERTIES", "TASK_RENT_MATCH_PROPERTIES", "TASK_INVEST_CONFIRM_OBJECTIVES", "TASK_INVEST_COMPARE_RETURNS", "TASK_INVEST_SCHEDULE_INSPECTION", "TASK_INVEST_INSPECTION_REPORT", "TASK_INVEST_VALIDATE_FINANCIALS"):
            if opp_id:
                await conn.execute(
                    "UPDATE opportunities SET stage = 'QUALIFIED', updated_at = NOW() WHERE opportunity_id = $1",
                    opp_id
                )
                opp_reverted = "QUALIFIED"

        elif tmpl_id == "TASK_INVEST_PREPARE_ACQUISITION_OFFER":
            if opp_id:
                await conn.execute(
                    "UPDATE opportunities SET stage = 'QUALIFIED', updated_at = NOW() WHERE opportunity_id = $1",
                    opp_id
                )
                opp_reverted = "QUALIFIED"
            if lead_id:
                await conn.execute("UPDATE leads SET status = 'QUALIFIED', updated_at = NOW() WHERE lead_id = $1", lead_id)
                lead_reverted = "QUALIFIED"

        # D) Viewing Schedule reversions
        elif tmpl_id in ("TASK_VIEWING_SCHEDULE", "TASK_VIEWING_RESCHEDULE", "TASK_RENT_VIEWING_FOLLOW_UP"):
            target_opp = opp_id
            if not target_opp and lead_id:
                target_opp = await conn.fetchval(
                    "SELECT opportunity_id FROM opportunities WHERE lead_id = $1 LIMIT 1", lead_id
                )
            if target_opp:
                # Cancel/Delete scheduled viewing that was created for this
                sch_viewing = await conn.fetchrow(
                    """
                    SELECT viewing_id FROM viewings
                    WHERE (opportunity_id = $1 OR lead_id = $2) AND status = 'SCHEDULED'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    target_opp, lead_id
                )
                if sch_viewing:
                    await conn.execute("DELETE FROM viewings WHERE viewing_id = $1", sch_viewing["viewing_id"])
                    viewing_reverted = f"Deleted Viewing {sch_viewing['viewing_id']}"

                # Revert opportunity stage if no other active viewings exist
                active_v = await conn.fetchval(
                    "SELECT count(*) FROM viewings WHERE opportunity_id = $1 AND status != 'CANCELLED'",
                    target_opp
                )
                if not active_v or active_v == 0:
                    await conn.execute(
                        "UPDATE opportunities SET stage = 'QUALIFIED', updated_at = NOW() WHERE opportunity_id = $1",
                        target_opp
                    )
                    opp_reverted = "QUALIFIED"

        # E) Viewing Report reversions
        elif tmpl_id == "TASK_VIEWING_REPORT":
            target_opp = opp_id
            if not target_opp and lead_id:
                target_opp = await conn.fetchval(
                    "SELECT opportunity_id FROM opportunities WHERE lead_id = $1 LIMIT 1", lead_id
                )
            # Revert viewing status back to SCHEDULED
            v_row = await conn.fetchrow(
                """
                SELECT viewing_id FROM viewings
                WHERE (opportunity_id = $1 OR lead_id = $2)
                ORDER BY updated_at DESC LIMIT 1
                """,
                target_opp, lead_id
            )
            if v_row:
                await conn.execute(
                    "UPDATE viewings SET status = 'SCHEDULED', outcome = NULL, updated_at = NOW() WHERE viewing_id = $1",
                    v_row["viewing_id"]
                )
                viewing_reverted = f"Restored Viewing {v_row['viewing_id']} to SCHEDULED"
            if target_opp:
                await conn.execute(
                    "UPDATE opportunities SET stage = 'VIEWING', updated_at = NOW() WHERE opportunity_id = $1",
                    target_opp
                )
                opp_reverted = "VIEWING"

        # 5. Remove or void the completion activity associated with this task
        await conn.execute(
            """
            DELETE FROM activities 
            WHERE task_id = $1 AND template_id != 'ACT_TASK_REOPENED'
            """,
            task_id
        )

        # 6. Revert target task back to PENDING
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'PENDING',
                completed_at = NULL
            WHERE task_id = $1
            """,
            task_id
        )

        # 7. Record Immutable Audit Activity ACT_TASK_REOPENED
        reopen_act = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_TASK_REOPENED",
            user_id=user_id,
            customer_id=cust_id,
            lead_id=lead_id,
            opportunity_id=opp_id,
            task_id=task_id,
            outcome="REOPENED",
            notes=reason or f"تم التراجع عن إكمال المهمة '{task['title']}' وإعادة فتحها وتصحيح المسار.",
            completed_at=now_dt
        )

        reopened_task = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)

        return {
            "reopened": True,
            "task_id": task_id,
            "title": task["title"],
            "status": "PENDING",
            "cancelled_downstream_tasks": cancelled_downstream,
            "lead_reverted_to": lead_reverted,
            "opportunity_reverted_to": opp_reverted,
            "viewing_reverted": viewing_reverted,
            "activity": reopen_act,
            "task": dict(reopened_task)
        }

    @staticmethod
    async def evaluate_sla_escalations(conn: asyncpg.Connection) -> Dict[str, Any]:
        """
        Background Worker Routine:
        Scans all pending tasks and applies the 30m / 45m SLA rules:
          - If due_at has passed and escalation_level == 0 -> escalation_level = 1 (Warning / Breached)
          - If due_at + 15 mins has passed and escalation_level <= 1:
              -> escalation_level = 2 (Escalated to Branch Manager)
              -> Look up branch manager and set escalated_to_user_id
        """
        now_dt = datetime.now(timezone.utc)

        # 1. Mark overdue tasks (Tier 1 Breach)
        tier1_updated = await conn.execute(
            """
            UPDATE tasks
            SET escalation_level = 1
            WHERE status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
              AND due_at < $1
              AND escalation_level = 0
            """,
            now_dt
        )

        # 2. Mark escalated to Branch Manager (Tier 2 Escalation at due_at + 15m)
        escalate_rows = await conn.fetch(
            """
            SELECT t.task_id, t.lead_id, t.assigned_user_id, l.branch_id
            FROM tasks t
            LEFT JOIN leads l ON t.lead_id = l.lead_id
            WHERE t.status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
              AND t.due_at + interval '15 minutes' < $1
              AND t.escalation_level < 2
            """,
            now_dt
        )

        escalated_count = 0
        for r in escalate_rows:
            branch_id = r["branch_id"]
            # Find Branch Manager
            bm_user_id = None
            if branch_id:
                bm_user_id = await conn.fetchval(
                    """
                    SELECT u.user_id 
                    FROM users u
                    JOIN user_roles ur ON u.user_id = ur.user_id
                    JOIN roles ro ON ur.role_id = ro.role_id
                    WHERE u.branch_id = $1 AND ro.role_code = 'SALES_MANAGER' AND u.status = 'ACTIVE'
                    LIMIT 1
                    """,
                    branch_id
                )

            await conn.execute(
                """
                UPDATE tasks
                SET escalation_level = 2, escalated_to_user_id = $1
                WHERE task_id = $2
                """,
                bm_user_id, r["task_id"]
            )
            escalated_count += 1

        return {
            "scanned_at": now_dt.isoformat(),
            "tier1_breaches": tier1_updated,
            "tier2_manager_escalations": escalated_count
        }

    @staticmethod
    async def get_entity_situation(
        conn: asyncpg.Connection,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Universal 360-Degree Operational Situation & Next Action Engine
        ==============================================================
        Compiles the complete lifecycle journey for any lead or opportunity:
        - Current status & stage
        - Responsible agent & branch manager
        - Full chronological milestone timeline (Tasks, Activities, Comms, Viewings, Offers, Contracts)
        - Bottleneck / Stalled Detection (identifies if a deal/lead has 0 open tasks)
        - Recommended 1-click unblock actions
        """
        now_dt = datetime.now(timezone.utc)
        lead_row = None
        opp_row = None
        customer_id = None

        if lead_id:
            lead_row = await conn.fetchrow(
                """
                SELECT l.*, c.first_name, c.last_name, c.company_name, c.mobile, c.email,
                       u.full_name as assigned_agent_name, mgr.full_name as manager_name,
                       pt.name_en as preferred_property_type_name_en,
                       pt.name_ar as preferred_property_type_name_ar
                FROM leads l
                LEFT JOIN customers c ON l.customer_id = c.customer_id
                LEFT JOIN users u ON l.assigned_user_id = u.user_id
                LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
                LEFT JOIN property_types pt ON l.preferred_property_type_id = pt.property_type_id
                WHERE l.lead_id = $1
                """,
                lead_id
            )
            if lead_row:
                customer_id = lead_row["customer_id"]
                if not opportunity_id:
                    opp_row = await conn.fetchrow(
                        """
                        SELECT o.*, u.full_name as assigned_agent_name, mgr.full_name as manager_name
                        FROM opportunities o
                        LEFT JOIN users u ON o.assigned_user_id = u.user_id
                        LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
                        WHERE o.lead_id = $1
                        ORDER BY o.created_at DESC LIMIT 1
                        """,
                        lead_id
                    )
                    if opp_row:
                        opportunity_id = opp_row["opportunity_id"]

        if opportunity_id and not opp_row:
            opp_row = await conn.fetchrow(
                """
                SELECT o.*, c.first_name, c.last_name, c.company_name, c.mobile, c.email,
                       u.full_name as assigned_agent_name, mgr.full_name as manager_name
                FROM opportunities o
                LEFT JOIN customers c ON o.customer_id = c.customer_id
                LEFT JOIN users u ON o.assigned_user_id = u.user_id
                LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
                WHERE o.opportunity_id = $1
                """,
                opportunity_id
            )
            if opp_row:
                customer_id = customer_id or opp_row["customer_id"]
                if not lead_row and opp_row["lead_id"]:
                    lead_id = opp_row["lead_id"]
                    lead_row = await conn.fetchrow(
                        """
                        SELECT l.*, c.first_name, c.last_name, c.company_name, c.mobile, c.email,
                               u.full_name as assigned_agent_name, mgr.full_name as manager_name,
                               pt.name_en as preferred_property_type_name_en,
                               pt.name_ar as preferred_property_type_name_ar
                        FROM leads l
                        LEFT JOIN customers c ON l.customer_id = c.customer_id
                        LEFT JOIN users u ON l.assigned_user_id = u.user_id
                        LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
                        LEFT JOIN property_types pt ON l.preferred_property_type_id = pt.property_type_id
                        WHERE l.lead_id = $1
                        """,
                        lead_id
                    )

        if not lead_row and not opp_row:
            raise ValueError(f"Entity not found (lead_id={lead_id}, opportunity_id={opportunity_id})")

        # 1. Fetch all tasks
        tasks = await conn.fetch(
            """
            SELECT t.*, u.full_name as assigned_user_name
            FROM tasks t
            LEFT JOIN users u ON t.assigned_user_id = u.user_id
            WHERE ($1::text IS NOT NULL AND t.lead_id = $1)
               OR ($2::text IS NOT NULL AND t.opportunity_id = $2)
               OR ($1::text IS NULL AND $2::text IS NULL AND $3::text IS NOT NULL AND t.customer_id = $3)
            ORDER BY t.created_at ASC
            """,
            lead_id, opportunity_id, customer_id
        )
        task_list = [dict(t) for t in tasks]

        # 2. Fetch all activities
        activities = await conn.fetch(
            """
            SELECT a.*, u.full_name as user_name
            FROM activities a
            LEFT JOIN users u ON a.user_id = u.user_id
            WHERE ($1::text IS NOT NULL AND a.lead_id = $1)
               OR ($2::text IS NOT NULL AND a.opportunity_id = $2)
               OR ($1::text IS NULL AND $2::text IS NULL AND $3::text IS NOT NULL AND a.customer_id = $3)
            ORDER BY a.created_at ASC
            """,
            lead_id, opportunity_id, customer_id
        )
        activity_list = [dict(a) for a in activities]

        # 3. Fetch communications
        communications = await conn.fetch(
            """
            SELECT * FROM communications
            WHERE ($1::text IS NOT NULL AND lead_id = $1)
               OR ($1::text IS NULL AND $2::text IS NOT NULL AND customer_id = $2)
            ORDER BY created_at ASC
            """,
            lead_id, customer_id
        )
        comm_list = [dict(c) for c in communications]

        # 4. Fetch viewings
        viewings = await conn.fetch(
            """
            SELECT v.*, u.unit_number, u.owner_customer_id,
                   COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                   owner_c.mobile AS unit_owner_mobile,
                   COALESCE(p.name_ar, p.name_en) as project_name, ag.full_name as agent_name
            FROM viewings v
            LEFT JOIN units u ON v.unit_id = u.unit_id
            LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
            LEFT JOIN buildings b ON u.building_id = b.building_id
            LEFT JOIN projects p ON b.project_id = p.project_id
            LEFT JOIN users ag ON v.agent_user_id = ag.user_id
            WHERE ($1::text IS NOT NULL AND v.opportunity_id = $1)
               OR ($2::text IS NOT NULL AND v.lead_id = $2)
               OR ($1::text IS NULL AND $2::text IS NULL AND $3::text IS NOT NULL AND v.customer_id = $3)
            ORDER BY v.created_at ASC
            """,
            opportunity_id, lead_id, customer_id
        )
        viewing_list = [dict(v) for v in viewings]

        # 5. Fetch offers
        offers = await conn.fetch(
            """
            SELECT o.*, u.unit_number, u.asking_price, u.owner_customer_id,
                   COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                   owner_c.mobile AS unit_owner_mobile
            FROM offers o
            LEFT JOIN units u ON o.unit_id = u.unit_id
            LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
            WHERE $1::text IS NOT NULL AND o.opportunity_id = $1
            ORDER BY o.valid_until DESC
            """,
            opportunity_id
        )
        offer_list = [dict(o) for o in offers]

        # 6. Fetch reservations & contracts (strictly scoped to opportunity, never broad customer)
        if opportunity_id:
            reservations = await conn.fetch(
                """
                SELECT r.*, u.unit_number, u.owner_customer_id,
                       COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                       owner_c.mobile AS unit_owner_mobile
                FROM reservations r
                LEFT JOIN units u ON r.unit_id = u.unit_id
                LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
                WHERE r.opportunity_id = $1
                ORDER BY r.reserved_at DESC
                """,
                opportunity_id
            )
            contracts = await conn.fetch(
                """
                SELECT c.*, u.unit_number, u.owner_customer_id,
                       COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                       owner_c.mobile AS unit_owner_mobile
                FROM contracts c
                JOIN reservations r ON c.reservation_id = r.reservation_id
                LEFT JOIN units u ON r.unit_id = u.unit_id
                LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
                WHERE r.opportunity_id = $1
                ORDER BY c.signed_at DESC NULLS LAST, c.contract_id DESC
                """,
                opportunity_id
            )
        elif not lead_id and customer_id:
            reservations = await conn.fetch(
                """
                SELECT r.*, u.unit_number, u.owner_customer_id,
                       COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                       owner_c.mobile AS unit_owner_mobile
                FROM reservations r
                LEFT JOIN units u ON r.unit_id = u.unit_id
                LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
                WHERE r.customer_id = $1
                ORDER BY r.reserved_at DESC
                """,
                customer_id
            )
            contracts = await conn.fetch(
                """
                SELECT c.*, u.unit_number, u.owner_customer_id,
                       COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                       owner_c.mobile AS unit_owner_mobile
                FROM contracts c
                JOIN reservations r ON c.reservation_id = r.reservation_id
                LEFT JOIN units u ON r.unit_id = u.unit_id
                LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
                WHERE r.customer_id = $1
                ORDER BY c.signed_at DESC NULLS LAST, c.contract_id DESC
                """,
                customer_id
            )
        else:
            reservations = []
            contracts = []

        res_list = [dict(r) for r in reservations]
        contract_list = [dict(c) for c in contracts]

        # 6.b Fetch tenancies (rental contracts) scoped to opportunity, lead, or customer
        tenancies = []
        if lead_id:
            tenancies = await conn.fetch(
                """
                SELECT t.*, u.unit_number, u.owner_customer_id,
                       COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                       owner_c.mobile AS unit_owner_mobile
                FROM tenancies t
                JOIN units u ON t.unit_id = u.unit_id
                LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
                WHERE t.tenant_customer_id = (SELECT customer_id FROM leads WHERE lead_id = $1)
                   OR t.unit_id = (SELECT unit_id FROM leads WHERE lead_id = $1)
                ORDER BY t.start_date DESC
                """,
                lead_id
            )
        elif opportunity_id:
            tenancies = await conn.fetch(
                """
                SELECT t.*, u.unit_number, u.owner_customer_id,
                       COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                       owner_c.mobile AS unit_owner_mobile
                FROM tenancies t
                JOIN units u ON t.unit_id = u.unit_id
                LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
                WHERE t.tenant_customer_id = (SELECT customer_id FROM opportunities WHERE opportunity_id = $1)
                   OR t.unit_id IN (SELECT unit_id FROM opportunity_units WHERE opportunity_id = $1)
                ORDER BY t.start_date DESC
                """,
                opportunity_id
            )
        elif customer_id:
            tenancies = await conn.fetch(
                """
                SELECT t.*, u.unit_number, u.owner_customer_id,
                       COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
                       owner_c.mobile AS unit_owner_mobile
                FROM tenancies t
                JOIN units u ON t.unit_id = u.unit_id
                LEFT JOIN customers owner_c ON u.owner_customer_id = owner_c.customer_id
                WHERE t.tenant_customer_id = $1
                ORDER BY t.start_date DESC
                """,
                customer_id
            )

        for t in tenancies:
            contract_list.append({
                "contract_id": t["tenancy_id"],
                "contract_number": t["contract_number"],
                "contract_type": "RENT",
                "unit_number": t["unit_number"],
                "unit_owner_name": t["unit_owner_name"],
                "unit_owner_mobile": t["unit_owner_mobile"],
                "owner_customer_id": t["owner_customer_id"],
                "contract_value": float(t["rent_amount"] or 0),
                "status": t["status"],
                "signed_at": t.get("created_at"),
                "start_date": t["start_date"],
                "end_date": t["end_date"]
            })

        all_contract_ids = [c["contract_id"] for c in contract_list]
        payment_list = []
        if all_contract_ids:
            p_rows = await conn.fetch(
                """
                SELECT p.*, c.contract_number
                FROM payments p
                JOIN contracts c ON p.contract_id = c.contract_id
                WHERE p.contract_id = ANY($1)
                ORDER BY p.due_date ASC
                """,
                all_contract_ids
            )
            for p in p_rows:
                payment_list.append({
                    "payment_id": p["payment_id"],
                    "reference": p["payment_reference"],
                    "contract_id": p["contract_id"],
                    "contract_number": p["contract_number"],
                    "type": "SALE_PAYMENT",
                    "due_date": p["due_date"].isoformat() if p.get("due_date") else None,
                    "paid_at": p["paid_at"].isoformat() if p.get("paid_at") else None,
                    "amount_due": float(p["amount_due"] or 0),
                    "amount_paid": float(p["amount_paid"] or 0),
                    "method": p.get("method") or "BANK_TRANSFER",
                    "status": p["status"],
                    "is_paid": (p["status"] == "PAID" or float(p["amount_paid"] or 0) >= float(p["amount_due"] or 0))
                })

        tenancy_ids = [t["tenancy_id"] for t in tenancies]
        if tenancy_ids:
            rc_rows = await conn.fetch(
                """
                SELECT rc.*, t.contract_number
                FROM rent_collections rc
                JOIN tenancies t ON rc.tenancy_id = t.tenancy_id
                WHERE rc.tenancy_id = ANY($1)
                ORDER BY rc.due_date ASC
                """,
                tenancy_ids
            )
            for rc in rc_rows:
                payment_list.append({
                    "payment_id": rc["rent_collection_id"],
                    "reference": rc["rent_collection_id"],
                    "contract_id": rc["tenancy_id"],
                    "contract_number": rc["contract_number"],
                    "type": "RENT_INSTALLMENT",
                    "due_date": rc["due_date"].isoformat() if rc.get("due_date") else None,
                    "paid_at": rc["paid_at"].isoformat() if rc.get("paid_at") else None,
                    "amount_due": float(rc["amount_due"] or 0),
                    "amount_paid": float(rc["amount_paid"] or 0),
                    "method": "RENT_COLLECTION",
                    "status": rc["status"],
                    "is_paid": (rc["status"] == "PAID" or float(rc["amount_paid"] or 0) >= float(rc["amount_due"] or 0))
                })

        # 6.d Fetch Commissions for linked sales & rental contracts
        commission_list = []
        con_nums = [c.get("contract_number") for c in contract_list if c.get("contract_number")]
        if all_contract_ids or con_nums:
            cm_rows = await conn.fetch(
                """
                SELECT cm.*, u.full_name as agent_name,
                       COALESCE(c.contract_number, cm.contract_id) as contract_number
                FROM commissions cm
                LEFT JOIN users u ON cm.user_id = u.user_id
                LEFT JOIN contracts c ON cm.contract_id = c.contract_id
                WHERE cm.contract_id = ANY($1::text[])
                   OR cm.contract_id IN (SELECT contract_id FROM contracts WHERE contract_number = ANY($2::text[]))
                   OR cm.contract_id IN (SELECT tenancy_id FROM tenancies WHERE contract_number = ANY($2::text[]))
                ORDER BY cm.commission_id ASC
                """,
                all_contract_ids, con_nums
            )
            for cm in cm_rows:
                commission_list.append({
                    "commission_id": cm["commission_id"],
                    "contract_id": cm["contract_id"],
                    "contract_number": cm.get("contract_number") or "--",
                    "agent_user_id": cm["user_id"],
                    "agent_name": cm.get("agent_name") or "Agent",
                    "commission_type": cm.get("commission_type") or "SALES",
                    "compensation_type": cm.get("compensation_type") or "COMMISSION",
                    "gross_deal_value": float(cm.get("gross_deal_value") or 0),
                    "gross_brokerage_amount": float(cm.get("gross_brokerage_amount") or 0),
                    "gov_fees_deducted": float(cm.get("gov_fees_deducted") or 0),
                    "net_commission_base": float(cm.get("net_commission_base") or 0),
                    "calculation_notes": cm.get("calculation_notes") or "",
                    "rate": float(cm["rate"] or 0),
                    "amount": float(cm["amount"] or 0),
                    "status": cm["status"],
                    "approved_at": cm["approved_at"].isoformat() if cm.get("approved_at") else None,
                    "paid_at": cm["paid_at"].isoformat() if cm.get("paid_at") else None,
                    "is_paid": (cm["status"] == "PAID")
                })

        # 6.e Fetch Statutory Saudi Fee Invoices (Customer vs. Owner)
        invoice_rows = await conn.fetch(
            """
            SELECT inv.*,
                   COALESCE(c.first_name || ' ' || c.last_name, c.company_name) as payer_customer_name,
                   c.mobile as payer_customer_mobile,
                   u.unit_number
            FROM invoices inv
            LEFT JOIN customers c ON inv.payer_customer_id = c.customer_id
            LEFT JOIN units u ON inv.unit_id = u.unit_id
            WHERE (
                ($1::text IS NOT NULL AND inv.opportunity_id = $1) OR
                ($2::text IS NOT NULL AND inv.lead_id = $2) OR
                (inv.contract_id = ANY($3::text[]))
            )
            ORDER BY inv.created_at ASC
            """,
            opportunity_id, lead_id, all_contract_ids
        )
        invoice_list = []
        for inv in invoice_rows:
            line_items = inv["line_items"]
            if isinstance(line_items, str):
                try:
                    line_items = json.loads(line_items)
                except Exception:
                    line_items = []
            invoice_list.append({
                "invoice_id": inv["invoice_id"],
                "invoice_number": inv["invoice_number"],
                "invoice_type": inv.get("invoice_type") or "TAX_INVOICE",
                "payer_type": inv["payer_type"],
                "payer_customer_id": inv["payer_customer_id"],
                "payer_name": inv.get("payer_customer_name") or ("العميل" if inv["payer_type"] == "CUSTOMER" else "المالك"),
                "payer_mobile": inv.get("payer_customer_mobile") or "",
                "opportunity_id": inv.get("opportunity_id"),
                "lead_id": inv.get("lead_id"),
                "contract_id": inv.get("contract_id"),
                "unit_id": inv.get("unit_id"),
                "unit_number": inv.get("unit_number") or "--",
                "transaction_type": inv.get("transaction_type") or "SALE",
                "subtotal": float(inv["subtotal"] or 0),
                "vat_rate": float(inv["vat_rate"] or 0),
                "vat_amount": float(inv["vat_amount"] or 0),
                "total_amount": float(inv["total_amount"] or 0),
                "amount_paid": float(inv["amount_paid"] or 0),
                "status": inv["status"],
                "is_paid": (inv["status"] == "PAID"),
                "situation": inv["status"],
                "line_items": line_items if isinstance(line_items, list) else [],
                "due_date": inv["due_date"].isoformat() if inv.get("due_date") else None,
                "paid_at": inv["paid_at"].isoformat() if inv.get("paid_at") else None,
                "payment_method": inv.get("payment_method"),
                "payment_reference": inv.get("payment_reference"),
                "notes": inv.get("notes"),
                "created_at": inv["created_at"].isoformat() if inv.get("created_at") else None
            })

        unpaid_invoices_count = len([inv for inv in invoice_list if not inv["is_paid"] and inv["status"] != "CANCELLED"])
        total_inv_amount = sum(inv["total_amount"] for inv in invoice_list if inv["status"] != "CANCELLED")
        total_inv_paid = sum(inv["amount_paid"] for inv in invoice_list if inv["status"] != "CANCELLED")

        # 7. Analyze Stalling & Bottleneck
        pending_tasks = [t for t in task_list if t["status"] in ("PENDING", "OPEN", "IN_PROGRESS")]
        
        current_stage = "UNKNOWN"
        is_terminal = False
        if contract_list:
            current_stage = f"CONTRACT ({contract_list[0]['status']})"
            if contract_list[0]["status"] in ("COMPLETED", "ACTIVE"):
                is_terminal = True
        elif res_list:
            current_stage = f"RESERVATION ({res_list[0]['status']})"
            if res_list[0]["status"] in ("CANCELLED", "EXPIRED"):
                is_terminal = False
        elif offer_list:
            current_stage = f"OFFER ({offer_list[0]['status']})"
        elif opp_row:
            current_stage = f"OPPORTUNITY ({opp_row['stage']})"
            if opp_row["stage"] in ("CLOSED_WON", "CLOSED_LOST"):
                is_terminal = True
        elif lead_row:
            current_stage = f"LEAD ({lead_row['status']})"
            if lead_row["status"] in ("CONVERTED", "DISQUALIFIED", "LOST"):
                is_terminal = True

        opp_stage = opp_row["stage"].upper() if (opp_row and opp_row.get("stage")) else None
        lead_status = lead_row["status"].upper() if (lead_row and lead_row.get("status")) else None

        is_stalled = (not is_terminal) and (len(pending_tasks) == 0)
        
        stalled_reason_ar = None
        stalled_reason_en = None
        recommended_actions = []

        if is_stalled:

            if opp_stage == "VIEWING":
                stalled_reason_ar = "الصفقة متوقفة في مرحلة المعاينة الميدانية (VIEWING) بدون أي مهمة نشطة أو موعد معاينة مؤكد حالياً."
                stalled_reason_en = "Deal is stalled at Viewing stage with no pending task or confirmed inspection visit."
                recommended_actions = [
                    {"action": "SPAWN_VIEWING_REPORT", "label_ar": "⭐ رفع تقرير المعاينة (إذا تمت الزيارة)", "label_en": "⭐ Submit Viewing Report"},
                    {"action": "SPAWN_VIEWING_SCHEDULE", "label_ar": "👁️ جدولة موعد معاينة ميدانية جديد", "label_en": "👁️ Schedule New Site Viewing"},
                    {"action": "SPAWN_OFFER_PREPARE", "label_ar": "💼 تقديم عرض مالي مباشرة (تخطي للتفاوض)", "label_en": "💼 Prepare Commercial Offer directly"}
                ]
            elif opp_stage == "NEGOTIATION":
                stalled_reason_ar = "الصفقة في مرحلة التفاوض ولكن لا يوجد عرض مالي قيد المتابعة."
                stalled_reason_en = "Deal is in Negotiation stage without an active offer proposal task."
                recommended_actions = [
                    {"action": "SPAWN_OFFER_PREPARE", "label_ar": "💼 إعداد وتقديم عرض مالي", "label_en": "💼 Prepare Commercial Offer"},
                    {"action": "SPAWN_RESERVATION_TASK", "label_ar": "🔒 الانتقال لحجز الوحدة مباشرة", "label_en": "🔒 Lock Unit Reservation"}
                ]
            elif opp_stage == "OFFER" or (offer_list and offer_list[0]["status"] == "SUBMITTED"):
                stalled_reason_ar = "تم تقديم العرض المالي ولكن لا توجد مهمة لمتابعة رد العميل قبل انتهاء المهلة."
                stalled_reason_en = "Commercial offer is active but has no pending follow-up task."
                recommended_actions = [
                    {"action": "SPAWN_OFFER_FOLLOWUP", "label_ar": "⏰ متابعة قرار العميل على العرض", "label_en": "⏰ Offer Decision Follow-up"},
                    {"action": "SPAWN_RESERVATION_TASK", "label_ar": "🔒 قبول العرض وحجز الوحدة", "label_en": "🔒 Accept Offer & Reserve"}
                ]
            elif opp_stage == "RESERVATION" or (res_list and res_list[0]["status"] == "ACTIVE"):
                stalled_reason_ar = "الوحدة محجوزة ولكن لا توجد مهمة متابعة لتحصيل العربون المالي."
                stalled_reason_en = "Unit is reserved but has no active deposit collection task."
                recommended_actions = [
                    {"action": "SPAWN_DEPOSIT_FOLLOWUP", "label_ar": "💰 متابعة سداد وتدقيق العربون", "label_en": "💰 Follow-up Earnest Deposit"},
                    {"action": "GENERATE_FEE_INVOICES", "label_ar": "🧾 إصدار فواتير الرسوم النظامية (العميل والمالك)", "label_en": "🧾 Generate Statutory Fee Invoices"},
                    {"action": "SPAWN_CONTRACT_DRAFT", "label_ar": "📝 البدء بصياغة مسودة العقد", "label_en": "📝 Initiate Contract Draft"}
                ]
            elif opp_stage in ("QUALIFIED", "MATCHING"):
                stalled_reason_ar = "الصفقة مؤهلة ولكن لم يتم ترشيح العقارات أو جدولة معاينة."
                stalled_reason_en = "Deal is qualified but property matching or viewing has not been scheduled."
                recommended_actions = [
                    {"action": "SPAWN_PROPERTY_MATCHING", "label_ar": "🏢 مطابقة وترشيح العقارات", "label_en": "🏢 Match Properties"},
                    {"action": "SPAWN_VIEWING_SCHEDULE", "label_ar": "👁️ جدولة موعد معاينة ميدانية", "label_en": "👁️ Schedule Site Viewing"}
                ]
            elif lead_status in ("NEW", "ASSIGNED"):
                stalled_reason_ar = "الطلب وارد ولكن لا توجد مهمة اتصال أولي نشطة للوسيط."
                stalled_reason_en = "Lead is assigned but has no active first contact task."
                recommended_actions = [
                    {"action": "SPAWN_FIRST_CONTACT", "label_ar": "📞 الاتصال الأولي بالعميل", "label_en": "📞 First Contact Attempt"}
                ]
            elif lead_status == "CONTACTED":
                stalled_reason_ar = "تم الاتصال بالعميل ولكن مهمة التأهيل لم تكتمل بعد."
                stalled_reason_en = "Client was contacted but qualification task is missing."
                recommended_actions = [
                    {"action": "SPAWN_QUALIFICATION", "label_ar": "⭐ استكمال معايير التأهيل", "label_en": "⭐ Complete Qualification"}
                ]
            else:
                stalled_reason_ar = "المعاملة مفتوحة ولكن لا توجد أي مهمة تنفيذية جارية حالياً."
                stalled_reason_en = "Record is active but has no pending tasks assigned."
                recommended_actions = [
                    {"action": "SPAWN_GENERAL_FOLLOWUP", "label_ar": "📋 إنشاء مهمة متابعة عامة", "label_en": "📋 Create General Follow-up Task"}
                ]

        # 8. Build Chronological Journey Timeline (including Tasks, Activities, Comms, Viewings, Offers, Reservations, Contracts)
        timeline = []
        for t in task_list:
            is_done = (t["status"] == "COMPLETED")
            t_ts = t.get("completed_at") if is_done else t.get("created_at")
            if not t_ts:
                t_ts = t.get("created_at") or t.get("due_at")
            timeline.append({
                "type": "TASK",
                "id": t["task_id"],
                "subject": t["title"],
                "description": f"المكلف: {t.get('assigned_user_name') or 'غير مسند'} | الحالة: {t['status']}",
                "status": t["status"],
                "is_done": is_done,
                "timestamp": t_ts.isoformat() if t_ts else None,
                "created_at": t["created_at"].isoformat() if t.get("created_at") else None,
                "due_at": t["due_at"].isoformat() if t.get("due_at") else None,
                "user_name": t.get("assigned_user_name") or "Agent"
            })
        for a in activity_list:
            is_done = (a.get("completed_at") is not None) or (a.get("status") == "COMPLETED")
            a_ts = a.get("completed_at") or a.get("created_at")
            timeline.append({
                "type": "ACTIVITY",
                "id": a["activity_id"],
                "subject": a["subject"],
                "description": a.get("description") or "",
                "outcome": a.get("outcome"),
                "status": a.get("status") or ("COMPLETED" if is_done else "PLANNED"),
                "is_done": is_done,
                "timestamp": a_ts.isoformat() if a_ts else None,
                "user_name": a.get("user_name") or "System/Agent"
            })
        for c in comm_list:
            is_done = (c.get("sent_at") is not None) or (c.get("delivery_status") in ("DELIVERED", "SENT"))
            c_ts = c.get("sent_at") or c.get("created_at")
            timeline.append({
                "type": "COMMUNICATION",
                "id": c["communication_id"],
                "subject": c.get("subject") or "Message",
                "description": c.get("body") or "",
                "channel": c.get("channel") or "SYSTEM",
                "direction": c.get("direction") or "OUT",
                "status": c.get("delivery_status") or "SENT",
                "is_done": is_done,
                "timestamp": c_ts.isoformat() if c_ts else None,
                "user_name": "System/Agent"
            })
        for v in viewing_list:
            is_done = (v.get("status") == "COMPLETED")
            v_ts = v.get("created_at") or v.get("scheduled_start")
            timeline.append({
                "type": "VIEWING",
                "id": v["viewing_id"],
                "subject": f"معاينة الوحدة #{v.get('unit_number') or '--'}",
                "description": f"المشروع: {v.get('project_name') or '--'} | الموعد: {v.get('scheduled_start')} | الحالة: {v.get('status')}",
                "status": v.get("status") or "SCHEDULED",
                "is_done": is_done,
                "outcome": v.get("outcome") or "--",
                "notes": v.get("notes") or "",
                "timestamp": v_ts.isoformat() if v_ts else None,
                "user_name": v.get("agent_name") or "Agent"
            })
        for o in offer_list:
            is_done = (o.get("status") in ("ACCEPTED", "REJECTED", "EXPIRED"))
            o_ts = o.get("submitted_at") or o.get("created_at")
            timeline.append({
                "type": "OFFER",
                "id": o["offer_id"],
                "subject": f"عرض مالي للوحدة #{o.get('unit_number') or '--'}",
                "description": f"المبلغ: {float(o['offer_amount'] or 0):,.2f} ريال. الحالة: {o.get('status')}",
                "status": o.get("status") or "SUBMITTED",
                "is_done": is_done,
                "timestamp": o_ts.isoformat() if o_ts else None,
                "user_name": "Sales Agent"
            })
        for r in res_list:
            is_done = (r.get("status") in ("ACTIVE", "CONVERTED_TO_CONTRACT", "COMPLETED"))
            r_ts = r.get("reserved_at") or r.get("created_at")
            timeline.append({
                "type": "RESERVATION",
                "id": r["reservation_id"],
                "subject": f"حجز الوحدة #{r.get('unit_number') or '--'}",
                "description": f"رقم الحجز: {r.get('reservation_number') or '--'}. العربون: {float(r['deposit_amount'] or 0):,.2f} ريال. الحالة: {r.get('status')}",
                "status": r.get("status") or "ACTIVE",
                "is_done": is_done,
                "timestamp": r_ts.isoformat() if r_ts else None,
                "user_name": "Operations"
            })
        for c in contract_list:
            is_done = (c.get("status") in ("ACTIVE", "COMPLETED", "SIGNED"))
            c_ts = c.get("signed_at") or c.get("created_at")
            timeline.append({
                "type": "CONTRACT",
                "id": c["contract_id"],
                "subject": f"عقد رقم {c.get('contract_number') or '--'}",
                "description": f"القيمة: {float(c['contract_value'] or 0):,.2f} ريال. الحالة: {c.get('status')}",
                "status": c.get("status") or "ACTIVE",
                "is_done": is_done,
                "timestamp": c_ts.isoformat() if c_ts else now_dt.isoformat(),
                "user_name": "Legal"
            })

        timeline.sort(key=lambda x: (1 if x.get("is_done") is False else 0, str(x.get("timestamp") or "")))

        # 9. Format Customer & Agent info & Lead Subject
        cust_name = ""
        cust_mobile = ""
        agent_name = ""
        mgr_name = ""
        lead_subject = ""
        inquiry_type = lead_row.get("inquiry_type") if lead_row else None
        lead_status = lead_row.get("status") if lead_row else None
        lead_priority = lead_row.get("priority") if lead_row else None
        lead_created_at = lead_row.get("created_at").isoformat() if (lead_row and lead_row.get("created_at")) else None
        preferred_property_type_id = lead_row.get("preferred_property_type_id") if lead_row else None
        preferred_property_type_name_ar = lead_row.get("preferred_property_type_name_ar") if lead_row else None
        preferred_property_type_name_en = lead_row.get("preferred_property_type_name_en") if lead_row else None

        if lead_row:
            cust_name = f"{lead_row['first_name'] or ''} {lead_row['last_name'] or ''}".strip() or lead_row["company_name"] or "Client"
            cust_mobile = lead_row["mobile"] or ""
            agent_name = lead_row["assigned_agent_name"] or ""
            mgr_name = lead_row["manager_name"] or ""
            lead_subject = f"طلب {inquiry_type or 'عقار'} — {cust_name}"
        elif opp_row:
            cust_name = f"{opp_row['first_name'] or ''} {opp_row['last_name'] or ''}".strip() or opp_row["company_name"] or "Client"
            cust_mobile = opp_row["mobile"] or ""
            agent_name = opp_row["assigned_agent_name"] or ""
            mgr_name = opp_row["manager_name"] or ""
            lead_subject = f"صفقة {opp_row.get('stage') or 'بيعية'} — {cust_name}"

        # 10. Format Detailed Structured Tables for Tabled UI Breakdown
        formatted_tasks = []
        for t in task_list:
            is_done = (t["status"] == "COMPLETED")
            due_dt = t.get("due_at")
            created_dt = t.get("created_at")
            completed_dt = t.get("completed_at")
            dt_sort = created_dt or completed_dt or due_dt
            formatted_tasks.append({
                "task_id": t["task_id"],
                "template_id": t.get("template_id"),
                "title": t["title"],
                "assigned_user_id": t.get("assigned_user_id"),
                "assigned_user_name": t.get("assigned_user_name") or "غير مسند",
                "assignee_name": t.get("assigned_user_name") or "غير مسند",
                "priority": t.get("priority") or "NORMAL",
                "status": t["status"],
                "is_done": is_done,
                "situation": "COMPLETED" if is_done else ("OVERDUE" if (due_dt and due_dt < now_dt and not is_done) else t["status"]),
                "due_at": due_dt.isoformat() if due_dt else None,
                "due_date": due_dt.isoformat() if due_dt else None,
                "created_at": created_dt.isoformat() if created_dt else None,
                "completed_at": completed_dt.isoformat() if completed_dt else None,
                "date_time": dt_sort.isoformat() if dt_sort else None
            })

        formatted_tasks.sort(key=lambda t: (1 if not t["is_done"] else 0, str(t.get("created_at") or "")))

        formatted_activities = []
        for a in activity_list:
            is_done = (a.get("completed_at") is not None) or (a.get("status") == "COMPLETED")
            c_dt = a.get("completed_at") or a.get("created_at")
            formatted_activities.append({
                "activity_id": a["activity_id"],
                "lead_id": a.get("lead_id") or lead_id,
                "activity_type": a.get("activity_type_code") or a.get("type") or "ACTIVITY",
                "subject": a["subject"],
                "description": a.get("description") or "",
                "outcome": a.get("outcome") or "--",
                "user_name": a.get("user_name") or "System/Agent",
                "status": a.get("status") or ("COMPLETED" if is_done else "PLANNED"),
                "is_done": is_done,
                "situation": "COMPLETED" if is_done else "PLANNED",
                "date_time": c_dt.isoformat() if c_dt else None
            })

        formatted_comms = []
        for c in comm_list:
            s_dt = c.get("sent_at") or c.get("created_at")
            is_done = (c.get("sent_at") is not None) or (c.get("delivery_status") in ("DELIVERED", "SENT"))
            formatted_comms.append({
                "communication_id": c["communication_id"],
                "lead_id": c.get("lead_id") or lead_id,
                "opportunity_id": c.get("opportunity_id") or opportunity_id,
                "channel": c.get("channel") or "SYSTEM",
                "direction": c.get("direction") or "OUT",
                "subject": c.get("subject") or "Message",
                "body": c.get("body") or "",
                "delivery_status": c.get("delivery_status") or "SENT",
                "is_done": is_done,
                "situation": c.get("delivery_status") or ("SENT" if is_done else "PENDING"),
                "date_time": s_dt.isoformat() if s_dt else None
            })

        formatted_viewings = []
        for v in viewing_list:
            is_done = (v.get("status") == "COMPLETED")
            v_dt = v.get("scheduled_start") or v.get("created_at")
            formatted_viewings.append({
                "viewing_id": v["viewing_id"],
                "unit_id": v.get("unit_id"),
                "unit_number": v.get("unit_number") or "--",
                "unit_owner_name": v.get("unit_owner_name"),
                "unit_owner_mobile": v.get("unit_owner_mobile"),
                "owner_customer_id": v.get("owner_customer_id"),
                "project_name": v.get("project_name") or "--",
                "agent_name": v.get("agent_name") or "Agent",
                "agent_user_id": v.get("agent_user_id"),
                "scheduled_start": v["scheduled_start"].isoformat() if v.get("scheduled_start") else None,
                "scheduled_end": v["scheduled_end"].isoformat() if v.get("scheduled_end") else None,
                "status": v.get("status") or "SCHEDULED",
                "outcome": v.get("outcome") or "--",
                "notes": v.get("notes") or "",
                "is_done": is_done,
                "situation": v.get("status") or "SCHEDULED",
                "date_time": v_dt.isoformat() if v_dt else None
            })

        formatted_offers = []
        for o in offer_list:
            is_done = (o.get("status") in ("ACCEPTED", "REJECTED", "EXPIRED"))
            o_dt = o.get("valid_until") or o.get("created_at")
            formatted_offers.append({
                "offer_id": o["offer_id"],
                "unit_id": o.get("unit_id"),
                "unit_number": o.get("unit_number") or "--",
                "unit_owner_name": o.get("unit_owner_name"),
                "unit_owner_mobile": o.get("unit_owner_mobile"),
                "owner_customer_id": o.get("owner_customer_id"),
                "offer_amount": float(o["offer_amount"]) if o.get("offer_amount") is not None else 0.0,
                "asking_price": float(o["asking_price"]) if o.get("asking_price") is not None else None,
                "status": o.get("status") or "SUBMITTED",
                "is_done": is_done,
                "situation": o.get("status") or "SUBMITTED",
                "valid_until": o["valid_until"].isoformat() if o.get("valid_until") else None,
                "date_time": o_dt.isoformat() if o_dt else None
            })

        formatted_reservations = []
        for r in res_list:
            is_done = (r.get("status") in ("ACTIVE", "CONVERTED_TO_CONTRACT", "COMPLETED"))
            r_dt = r.get("reserved_at")
            formatted_reservations.append({
                "reservation_id": r["reservation_id"],
                "reservation_number": r.get("reservation_number") or "--",
                "unit_id": r.get("unit_id"),
                "unit_number": r.get("unit_number") or "--",
                "unit_owner_name": r.get("unit_owner_name"),
                "unit_owner_mobile": r.get("unit_owner_mobile"),
                "owner_customer_id": r.get("owner_customer_id"),
                "deposit_amount": float(r["deposit_amount"]) if r.get("deposit_amount") is not None else 0.0,
                "status": r.get("status") or "ACTIVE",
                "is_done": is_done,
                "situation": r.get("status") or "ACTIVE",
                "reserved_at": r_dt.isoformat() if r_dt else None,
                "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                "date_time": r_dt.isoformat() if r_dt else None
            })

        formatted_contracts = []
        for c in contract_list:
            is_done = (c.get("status") in ("ACTIVE", "COMPLETED", "SIGNED"))
            c_dt = c.get("signed_at") or c.get("start_date")
            formatted_contracts.append({
                "contract_id": c["contract_id"],
                "contract_number": c.get("contract_number") or "--",
                "contract_type": c.get("contract_type") or "SALE",
                "unit_number": c.get("unit_number") or "--",
                "unit_owner_name": c.get("unit_owner_name"),
                "unit_owner_mobile": c.get("unit_owner_mobile"),
                "owner_customer_id": c.get("owner_customer_id"),
                "contract_value": float(c["contract_value"]) if c.get("contract_value") is not None else 0.0,
                "status": c.get("status") or "ACTIVE",
                "is_done": is_done,
                "situation": c.get("status") or "ACTIVE",
                "signed_at": c["signed_at"].isoformat() if c.get("signed_at") else None,
                "start_date": c["start_date"].isoformat() if c.get("start_date") else None,
                "end_date": c["end_date"].isoformat() if c.get("end_date") else None,
                "date_time": c_dt.isoformat() if (c_dt and hasattr(c_dt, 'isoformat')) else (str(c_dt) if c_dt else None)
            })

        # Format pending tasks list (backward compatibility)
        formatted_pending = [t for t in formatted_tasks if not t["is_done"]]

        # 11. Compile Universal Active Guidance & Responsibility SOP Card from DB table
        target_stage_code = "NEW"
        if opp_stage == "CLOSED_WON" or (contract_list and contract_list[0].get("status") in ("ACTIVE", "SIGNED", "COMPLETED")):
            target_stage_code = "CLOSED_WON"
        elif opp_stage == "CONTRACT" or (res_list and res_list[0].get("deposit_status") == "VERIFIED"):
            target_stage_code = "CONTRACT"
        elif opp_stage == "RESERVATION" or (res_list and res_list[0].get("status") == "ACTIVE"):
            target_stage_code = "RESERVATION"
        elif opp_stage in ("OFFER", "NEGOTIATION") or offer_list:
            target_stage_code = "OFFER"
        elif opp_stage == "VIEWING" or viewing_list:
            target_stage_code = "VIEWING"
        elif opp_stage in ("QUALIFIED", "MATCHING"):
            target_stage_code = "QUALIFIED"
        else:
            target_stage_code = "NEW"

        # Determine active task template if available
        active_pending_task = formatted_pending[0] if formatted_pending else None
        active_template_id = active_pending_task.get("template_id") if active_pending_task else None

        guidance_row = None
        if active_template_id:
            guidance_row = await conn.fetchrow("""
                SELECT g.*, r.name_ar AS role_name_ar, r.name_en AS role_name_en
                FROM workflow_sop_guidance g
                LEFT JOIN roles r ON g.responsible_role_code = r.role_code
                WHERE (g.template_id = $1 OR g.procedure_code = $1) AND g.is_active = TRUE
                ORDER BY g.display_order ASC LIMIT 1
            """, active_template_id)

        if not guidance_row:
            guidance_row = await conn.fetchrow("""
                SELECT g.*, r.name_ar AS role_name_ar, r.name_en AS role_name_en
                FROM workflow_sop_guidance g
                LEFT JOIN roles r ON g.responsible_role_code = r.role_code
                WHERE g.stage_code = $1 AND g.entity_type = 'STAGE' AND g.is_active = TRUE
                ORDER BY g.display_order ASC LIMIT 1
            """, target_stage_code)

        if not guidance_row:
            guidance_row = await conn.fetchrow("""
                SELECT g.*, r.name_ar AS role_name_ar, r.name_en AS role_name_en
                FROM workflow_sop_guidance g
                LEFT JOIN roles r ON g.responsible_role_code = r.role_code
                WHERE g.stage_code = $1 AND g.is_active = TRUE
                ORDER BY g.display_order ASC LIMIT 1
            """, target_stage_code)

        if guidance_row:
            active_guidance = dict(guidance_row)
            active_guidance["stage_key"] = target_stage_code
            
            # Dynamically resolve current_responsible_ar / en from canonical roles and live assigned employee
            role_ar = active_guidance.get("role_name_ar") or "المسؤول المختص"
            role_en = active_guidance.get("role_name_en") or "Authorized Role"
            assigned_person = None
            if active_pending_task and active_pending_task.get("assigned_user_name"):
                assigned_person = active_pending_task["assigned_user_name"]
            elif agent_name:
                assigned_person = agent_name

            if assigned_person and assigned_person not in ("غير مسند", "Unassigned"):
                active_guidance["current_responsible_ar"] = f"{assigned_person} ({role_ar})"
                active_guidance["current_responsible_en"] = f"{assigned_person} ({role_en})"
            else:
                active_guidance["current_responsible_ar"] = role_ar
                active_guidance["current_responsible_en"] = role_en

            if target_stage_code == "RESERVATION" and res_list:
                active_res = res_list[0]
                res_no = active_res.get("reservation_number") or "--"
                dep_val = float(active_res.get("deposit_amount") or 0)
                active_guidance["stage_name_ar"] = f"الحجز المالي والعربون (رقم الحجز: {res_no})"
                active_guidance["stage_name_en"] = f"Unit Reservation & Deposit (Ref: {res_no})"
                active_guidance["required_now_ar"] = f"بانتظار سداد العربون ({dep_val:,.2f} ر.س) وتدقيق المحاسبة"
                active_guidance["required_now_en"] = f"Awaiting earnest deposit payment ({dep_val:,.2f} SAR) & accounting audit"
            for f in ("execution_steps_ar", "execution_steps_en"):
                val = active_guidance.get(f)
                while isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except Exception:
                        break
                active_guidance[f] = val if isinstance(val, list) else []
        else:
            active_guidance = {}

        # Fetch all procedures defined for this lifecycle stage
        stage_procs_rows = await conn.fetch("""
            SELECT g.*, r.name_ar AS role_name_ar, r.name_en AS role_name_en
            FROM workflow_sop_guidance g
            LEFT JOIN roles r ON g.responsible_role_code = r.role_code
            WHERE g.stage_code = $1 AND g.is_active = TRUE
            ORDER BY g.display_order ASC
        """, target_stage_code)
        stage_procedures = []
        for sp in stage_procs_rows:
            sp_dict = dict(sp)
            sp_role_ar = sp_dict.get("role_name_ar") or ""
            sp_role_en = sp_dict.get("role_name_en") or ""
            sp_dict["current_responsible_ar"] = sp_role_ar
            sp_dict["current_responsible_en"] = sp_role_en
            for f in ("execution_steps_ar", "execution_steps_en"):
                val = sp_dict.get(f)
                while isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except Exception:
                        break
                sp_dict[f] = val if isinstance(val, list) else []
            stage_procedures.append(sp_dict)

        # 12. Format Detailed Structured Payments Breakdown
        formatted_payments = []
        for p in payment_list:
            formatted_payments.append({
                "payment_id": p["payment_id"],
                "reference": p["reference"],
                "contract_id": p["contract_id"],
                "contract_number": p.get("contract_number") or "--",
                "payment_type": p.get("type") or "PAYMENT",
                "due_date": p.get("due_date"),
                "paid_at": p.get("paid_at"),
                "amount_due": p["amount_due"],
                "amount_paid": p["amount_paid"],
                "method": p.get("method") or "--",
                "status": p["status"],
                "is_paid": p.get("is_paid", False),
                "situation": p["status"]
            })

        # 13. Format Detailed Structured Commissions Breakdown
        formatted_commissions = []
        for cm in commission_list:
            formatted_commissions.append({
                "commission_id": cm["commission_id"],
                "contract_id": cm["contract_id"],
                "contract_number": cm.get("contract_number") or "--",
                "agent_name": cm.get("agent_name") or "Agent",
                "agent_user_id": cm.get("agent_user_id"),
                "commission_type": cm.get("commission_type") or "SALES",
                "compensation_type": cm.get("compensation_type") or "COMMISSION",
                "gross_deal_value": cm.get("gross_deal_value") or 0.0,
                "gross_brokerage_amount": cm.get("gross_brokerage_amount") or 0.0,
                "gov_fees_deducted": cm.get("gov_fees_deducted") or 0.0,
                "net_commission_base": cm.get("net_commission_base") or 0.0,
                "calculation_notes": cm.get("calculation_notes") or "",
                "rate": cm.get("rate") or 0.0,
                "amount": cm["amount"],
                "status": cm["status"],
                "is_paid": cm.get("is_paid", False),
                "approved_at": cm.get("approved_at"),
                "paid_at": cm.get("paid_at"),
                "situation": cm["status"]
            })

        total_contract_val = sum(float(c.get("contract_value") or 0) for c in formatted_contracts)
        total_paid_val = sum(float(p.get("amount_paid") or 0) for p in formatted_payments)
        total_due_val = sum(float(p.get("amount_due") or 0) for p in formatted_payments)
        total_comm_val = sum(float(cm.get("amount") or 0) for cm in formatted_commissions)

        return {
            "active_guidance": active_guidance,
            "lead_id": lead_id,
            "opportunity_id": opportunity_id,
            "customer_id": customer_id,
            "customer_name": cust_name,
            "customer_mobile": cust_mobile,
            "assigned_agent_name": agent_name,
            "manager_name": mgr_name,
            "lead_subject": lead_subject,
            "inquiry_type": inquiry_type,
            "lead_status": lead_status,
            "lead_priority": lead_priority,
            "lead_created_at": lead_created_at,
            "preferred_property_type_id": preferred_property_type_id,
            "preferred_property_type_name_ar": preferred_property_type_name_ar,
            "preferred_property_type_name_en": preferred_property_type_name_en,
            "current_stage": current_stage,
            "is_stalled": is_stalled,
            "stalled_reason_ar": stalled_reason_ar,
            "stalled_reason_en": stalled_reason_en,
            "recommended_actions": recommended_actions,
            "timeline": timeline,
            "tasks": formatted_tasks,
            "activities": formatted_activities,
            "communications": formatted_comms,
            "viewings": formatted_viewings,
            "offers": formatted_offers,
            "reservations": formatted_reservations,
            "contracts": formatted_contracts,
            "payments": formatted_payments,
            "commissions": formatted_commissions,
            "invoices": invoice_list,
            "invoices_count": len(invoice_list),
            "unpaid_invoices_count": unpaid_invoices_count,
            "total_invoices_amount": total_inv_amount,
            "total_invoices_paid": total_inv_paid,
            "has_unpaid_statutory_fees": (unpaid_invoices_count > 0),
            "payments_count": len(formatted_payments),
            "commissions_count": len(formatted_commissions),
            "total_contract_value": total_contract_val,
            "total_amount_paid": total_paid_val,
            "total_amount_due": total_due_val,
            "total_commission_amount": total_comm_val,
            "stage_procedures": stage_procedures,
            "stage_procedures_count": len(stage_procedures),
            "pending_tasks": formatted_pending,
            "completed_tasks_count": len([t for t in formatted_tasks if t["is_done"]]),
            "activities_count": len(formatted_activities),
            "communications_count": len(formatted_comms),
            "viewings_count": len(formatted_viewings),
            "offers_count": len(formatted_offers),
            "reservations_count": len(formatted_reservations),
            "contracts_count": len(formatted_contracts)
        }

    @staticmethod
    async def unblock_entity_situation(
        conn: asyncpg.Connection,
        action: str,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        user_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a 1-click unblock action on any stalled lead or opportunity.
        """
        now_dt = datetime.now(timezone.utc)
        lead_row = None
        opp_row = None
        if lead_id:
            lead_row = await conn.fetchrow("SELECT * FROM leads WHERE lead_id = $1", lead_id)
            if not opportunity_id:
                opp_row = await conn.fetchrow("SELECT * FROM opportunities WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 1", lead_id)
                if opp_row:
                    opportunity_id = opp_row["opportunity_id"]
        if opportunity_id and not opp_row:
            opp_row = await conn.fetchrow("SELECT * FROM opportunities WHERE opportunity_id = $1", opportunity_id)
            if opp_row and not lead_row and opp_row["lead_id"]:
                lead_id = opp_row["lead_id"]
                lead_row = await conn.fetchrow("SELECT * FROM leads WHERE lead_id = $1", lead_id)

        customer_id = (opp_row["customer_id"] if opp_row else None) or (lead_row["customer_id"] if lead_row else None)
        agent_id = (opp_row["assigned_user_id"] if opp_row else None) or (lead_row["assigned_user_id"] if lead_row else None) or user_id

        norm_act = action.strip().upper()
        spawned_task = None

        if norm_act == "SPAWN_VIEWING_REPORT":
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "SPAWN_VIEWING_SCHEDULE":
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_VIEWING_SCHEDULE",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "SPAWN_OFFER_PREPARE":
            if opportunity_id:
                await conn.execute("UPDATE opportunities SET stage = 'NEGOTIATION', updated_at = NOW() WHERE opportunity_id = $1", opportunity_id)
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OFFER_PREPARE",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "SPAWN_OFFER_FOLLOWUP":
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OFFER_FOLLOWUP",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "SPAWN_PROPERTY_MATCHING":
            if opportunity_id:
                await conn.execute("UPDATE opportunities SET stage = 'MATCHING', updated_at = NOW() WHERE opportunity_id = $1", opportunity_id)
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OPPORTUNITY_MATCH_PROPERTIES",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="NORMAL"
            )
        elif norm_act == "SPAWN_RESERVATION_TASK":
            if opportunity_id:
                await conn.execute("UPDATE opportunities SET stage = 'UNDER_OFFER', updated_at = NOW() WHERE opportunity_id = $1", opportunity_id)
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_RESERVATION_VERIFY_AVAILABILITY",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="URGENT"
            )
        elif norm_act == "SPAWN_DEPOSIT_FOLLOWUP":
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_RESERVATION_DEPOSIT_FOLLOWUP",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "SPAWN_CONTRACT_DRAFT":
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_CONTRACT_DRAFT",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "SPAWN_FIRST_CONTACT":
            first_contact_template = "TASK_LEAD_FIRST_CONTACT"
            if lead_row:
                inq_type = (lead_row.get("inquiry_type") or "").upper()
                if inq_type == "RENT":
                    first_contact_template = "TASK_RENT_LEAD_FIRST_CONTACT"
                elif inq_type == "INVESTMENT":
                    first_contact_template = "TASK_INVEST_LEAD_FIRST_CONTACT"
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=first_contact_template,
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "SPAWN_QUALIFICATION":
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_LEAD_QUALIFY",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="HIGH"
            )
        elif norm_act == "GENERATE_FEE_INVOICES":
            res = await WorkflowEngine.generate_saudi_fee_invoices(
                conn=conn,
                opportunity_id=opportunity_id,
                lead_id=lead_id,
                user_id=user_id or agent_id
            )
            spawned_task = res.get("task")
        else:
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_LEAD_FOLLOWUP",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_id,
                priority="NORMAL"
            )

        # Log activity
        await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_LEAD_FOLLOWUP",
            user_id=user_id or agent_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            outcome="RESUMED",
            notes=notes or f"تم تنشيط مسار المعاملة وتوليد مهمة: {spawned_task['title'] if spawned_task else norm_act}",
            completed_at=now_dt
        )

        return {
            "action": norm_act,
            "lead_id": lead_id,
            "opportunity_id": opportunity_id,
            "spawned_task": spawned_task,
            "resumed_at": now_dt.isoformat()
        }


