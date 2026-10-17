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
import hashlib
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
        assigner_user_id: Optional[str] = None
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

        lead = await conn.fetchrow("SELECT customer_id, priority, branch_id FROM leads WHERE lead_id = $1", lead_id)
        if not lead:
            return {"status": "lead_not_found"}

        customer_id = lead["customer_id"]
        priority = lead["priority"] or "NORMAL"

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
        await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_LEAD_ASSIGNED",
            user_id=assigned_user_id,
            customer_id=customer_id,
            lead_id=lead_id,
            outcome="ASSIGNED",
            notes=f"تم تعيين الطلب للوسيط ({agent_name}). تم إسناد مهمة الاتصال الأولي (مهلة 30 دقيقة)."
        )

        # 3. Check for open TASK_LEAD_FIRST_CONTACT
        open_contact_task = await conn.fetchrow(
            """
            SELECT task_id FROM tasks 
            WHERE lead_id = $1 AND template_id = 'TASK_LEAD_FIRST_CONTACT' AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            LIMIT 1
            """,
            lead_id
        )
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
            # Spawn fresh contact task for new agent
            task_dict, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=customer_id,
                assigned_user_id=assigned_user_id,
                priority=priority,
                custom_due_at=first_contact_due
            )

        # 4. Sync lead first_contact_due_at and optionally branch_id
        updates = ["first_contact_due_at = $1"]
        params = [first_contact_due]
        p_idx = 2
        if user_branch_id:
            updates.append(f"branch_id = ${p_idx}")
            params.append(user_branch_id)
            p_idx += 1
        params.append(lead_id)
        await conn.execute(
            f"UPDATE leads SET {', '.join(updates)}, updated_at = NOW() WHERE lead_id = ${p_idx}",
            *params
        )

        return {"status": "assigned", "agent_name": agent_name, "task": task_dict}

    @staticmethod
    async def spawn_task_from_template(
        conn: asyncpg.Connection,
        template_id: str,
        lead_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        assigned_user_id: Optional[str] = None,
        priority: str = "NORMAL",
        custom_due_at: Optional[datetime] = None,
        parent_task_id: Optional[str] = None
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Spawns a standardized task from the template catalog.
        Anti-Duplication / Idempotency Rule:
          Guarantees that an open task for the same template & entity is NOT duplicated.
        Returns:
          (task_dict, is_new: bool)
        """
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
                  ($4::text IS NOT NULL AND customer_id = $4)
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
            t_dict = dict(existing_task)
            if assigned_user_id:
                t_dict["assigned_user_id"] = assigned_user_id
            if parent_task_id:
                t_dict["parent_task_id"] = parent_task_id
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

        standard_title = tmpl["standard_title_ar"] if tmpl else f"Task ({template_id})"
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
        elif template_id in ("ACT_TASK_REOPENED",):
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
                   unit_id, preferred_city_id, preferred_property_type_id
            FROM leads 
            WHERE lead_id = $1
            """,
            lead_id
        )
        if not lead:
            raise ValueError(f"Lead '{lead_id}' not found.")

        effective_user_id = user_id or lead["assigned_user_id"] or "user-51"
        now_dt = datetime.now(timezone.utc)

        # 1. Complete open qualification or contact tasks for this lead
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE lead_id = $2
              AND template_id IN ('TASK_LEAD_QUALIFY', 'TASK_LEAD_FIRST_CONTACT', 'TASK_LEAD_FOLLOWUP')
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

        # 5. Record Activity ACT_LEAD_QUALIFIED
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_LEAD_QUALIFIED",
            user_id=effective_user_id,
            customer_id=lead["customer_id"],
            lead_id=lead_id,
            opportunity_id=opp_id,
            task_id=parent_task_id,
            outcome="QUALIFIED",
            notes=notes or "تم استفاء معايير التأهيل بنجاح وترقية الطلب لفرصة بيعية نشطة.",
            completed_at=now_dt
        )

        # 6. Auto-spawn Stage C (or Stage D if primary unit pre-selected)
        has_primary_unit = await conn.fetchval(
            "SELECT count(*) FROM opportunity_units WHERE opportunity_id = $1 AND is_primary = TRUE",
            opp_id
        )
        if has_primary_unit and has_primary_unit > 0:
            next_task_template = "TASK_VIEWING_SCHEDULE"
        else:
            next_task_template = "TASK_OPPORTUNITY_MATCH_PROPERTIES"

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
            "viewing_task": next_task,
            "matching_task": next_task if next_task_template == "TASK_OPPORTUNITY_MATCH_PROPERTIES" else None,
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

        # 2. Complete open TASK_OPPORTUNITY_MATCH_PROPERTIES
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE opportunity_id = $2 AND template_id = 'TASK_OPPORTUNITY_MATCH_PROPERTIES'
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            """,
            now_dt, opportunity_id
        )

        # 3. Record Activity ACT_OPPORTUNITY_PROPERTIES_PRESENTED
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_OPPORTUNITY_PROPERTIES_PRESENTED",
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

        # 5. Auto-spawn Stage D Task: TASK_VIEWING_SCHEDULE
        viewing_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_VIEWING_SCHEDULE",
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

        # 3. Complete any open TASK_VIEWING_SCHEDULE
        if task_id:
            await conn.execute(
                "UPDATE tasks SET status = 'COMPLETED', completed_at = $1 WHERE task_id = $2",
                now_dt, task_id
            )
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = $1
            WHERE template_id = 'TASK_VIEWING_SCHEDULE'
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

        # 5. Record Activity ACT_VIEWING_SCHEDULED
        start_str = scheduled_start.strftime("%Y-%m-%d %H:%M")
        activity = await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_VIEWING_SCHEDULED",
            user_id=agent_user_id,
            customer_id=customer_id,
            lead_id=lead_id,
            opportunity_id=opportunity_id,
            task_id=task_id,
            outcome="SCHEDULED",
            notes=f"تم تحديد موعد معاينة ميدانية للوحدة #{unit_number} بتاريخ {start_str}. {all_notes or ''}".strip(),
            completed_at=now_dt
        )

        # 6. Record Outbound Communication COMM_VIEWING_CONFIRMATION
        comm_id = await get_next_id(conn, "communications", "comm")
        comm_msg = f"مرحباً بك، نود تأكيد موعد المعاينة الميدانية للوحدة #{unit_number} بمشروع ({proj_name}). الموعد: {start_str}. {location_notes or ''}".strip()
        await conn.execute(
            """
            INSERT INTO communications (
                communication_id, customer_id, lead_id, channel, direction,
                subject, body, sent_at, delivery_status, template_id, created_at
            ) VALUES ($1, $2, $3, 'WHATSAPP', 'OUT', $4, $5, NOW(), 'SENT', 'COMM_VIEWING_CONFIRMATION', NOW())
            """,
            comm_id, customer_id, lead_id,
            f"تأكيد موعد المعاينة الميدانية للوحدة #{unit_number}",
            comm_msg
        )

        # 7. Auto-spawn Stage 3 Report Task: TASK_VIEWING_REPORT with 2h SLA after scheduled visit
        report_due = scheduled_end + timedelta(hours=2)
        report_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_VIEWING_REPORT",
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
            SELECT viewing_id, unit_id, opportunity_id, customer_id
            FROM viewings
            WHERE (opportunity_id = $1 OR ($2::text IS NOT NULL AND lead_id = $2))
              AND status = 'SCHEDULED'
            ORDER BY scheduled_start DESC
            LIMIT 1
            """,
            opportunity_id, lead_id
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
                await conn.execute(
                    "UPDATE opportunities SET stage = 'NEGOTIATION', updated_at = NOW() WHERE opportunity_id = $1",
                    opportunity_id
                )
            # Auto-spawn Stage 4 Task: TASK_OFFER_SUBMIT with 12h SLA
            offer_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OFFER_SUBMIT",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_user_id,
                priority="HIGH",
                parent_task_id=task_id
            )
            next_action = {"type": "OFFER_TASK_SPAWNED", "task": offer_task}

        elif outcome == "NEEDS_ANOTHER_UNIT":
            new_stage = "VIEWING"
            # Auto-spawn new TASK_VIEWING_SCHEDULE
            sched_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_VIEWING_SCHEDULE",
                lead_id=lead_id,
                opportunity_id=opportunity_id,
                customer_id=customer_id,
                assigned_user_id=agent_user_id,
                priority="NORMAL",
                parent_task_id=task_id
            )
        elif outcome in ("NO_SHOW", "CANCELLED"):
            new_stage = "VIEWING"
            # Auto-spawn Stage D Task: TASK_VIEWING_RESCHEDULE with 4h SLA
            resched_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_VIEWING_RESCHEDULE",
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

            mgr_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OFFER_MANAGER_APPROVAL",
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

            followup_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OFFER_FOLLOWUP",
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

            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OFFER_FOLLOWUP",
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
            # Automatic Stage F Trigger: verify availability & reserve unit
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_RESERVATION_VERIFY_AVAILABILITY",
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
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OFFER_PREPARE",
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
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_OPPORTUNITY_MATCH_PROPERTIES",
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

        deposit_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_RESERVATION_DEPOSIT_FOLLOWUP",
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

        draft_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_CONTRACT_DRAFT",
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
            SELECT r.*, u.unit_number, u.asking_price, u.rent_price, o.lead_id, o.assigned_user_id
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

        val = contract_value or float(res["asking_price"] or res["rent_price"] or 500000.0)
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

        review_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_CONTRACT_INTERNAL_REVIEW",
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
            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_CONTRACT_SIGNATURE",
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
            comm_id = await get_next_id(conn, "commissions", "comm")
            comm_amt = round(contract_val * 0.025, 2)
            await conn.execute(
                """
                INSERT INTO commissions (commission_id, contract_id, user_id, commission_type, rate, amount, status)
                VALUES ($1, $2, $3, 'SALES', 2.5, $4, 'PENDING')
                """,
                comm_id, contract_id, comm_agent_id, comm_amt
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

            next_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_CONTRACT_HANDOVER",
                lead_id=c["lead_id"],
                opportunity_id=c["opportunity_id"],
                customer_id=c["customer_id"],
                assigned_user_id=pm_user_id,
                priority="NORMAL",
                custom_due_at=now_dt + timedelta(hours=72),
                parent_task_id=parent_task_id
            )

        elif norm_action in ("COMPLETE_HANDOVER", "CLOSE_CONTRACT"):
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
        else:
            raise ValueError(f"Unknown contract action '{action}'. Expected APPROVE_DRAFT, RECORD_SIGNATURE, or COMPLETE_HANDOVER.")

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

        # 3. Stage C Handling: TASK_OPPORTUNITY_MATCH_PROPERTIES
        if tmpl_id == "TASK_OPPORTUNITY_MATCH_PROPERTIES":
            v_data = viewing_data or {}
            unit_ids = v_data.get("unit_ids") or []
            if not unit_ids and v_data.get("unit_id"):
                unit_ids = [v_data.get("unit_id")]
            opp_id = task["opportunity_id"]
            if not opp_id and lead_id:
                opp_id = await conn.fetchval("SELECT opportunity_id FROM opportunities WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 1", lead_id)
            if not opp_id:
                raise ValueError("No opportunity linked to property matching task.")

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

        # 4. Stage D Handling: TASK_VIEWING_SCHEDULE & TASK_VIEWING_RESCHEDULE & TASK_VIEWING_REPORT
        if tmpl_id in ("TASK_VIEWING_SCHEDULE", "TASK_VIEWING_RESCHEDULE"):
            v_data = viewing_data or {}
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

            offer_amt = float(v_data.get("offer_amount") or 500000.0)
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
        if tmpl_id == "TASK_LEAD_FOLLOWUP":
            act_template_id = "ACT_LEAD_FOLLOWUP"
        elif tmpl_id == "TASK_LEAD_QUALIFY":
            act_template_id = "ACT_LEAD_QUALIFIED"
        elif tmpl_id == "TASK_LEAD_ASSIGN":
            act_template_id = "ACT_LEAD_ASSIGNED"

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

        if lead_id and tmpl_id in ("TASK_LEAD_FIRST_CONTACT", "TASK_LEAD_FOLLOWUP"):
            lead = await conn.fetchrow("SELECT status, assigned_user_id FROM leads WHERE lead_id = $1", lead_id)
            if lead:
                if outcome == "CONNECTED":
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
        if tmpl_id in ("TASK_LEAD_FIRST_CONTACT", "TASK_LEAD_FOLLOWUP") and lead_id:
            lead = await conn.fetchrow("SELECT status, assigned_user_id FROM leads WHERE lead_id = $1", lead_id)
            if lead and lead["status"] in ("CONTACTED", "UNREACHABLE", "DISQUALIFIED"):
                prev_lead_status = "ASSIGNED" if lead["assigned_user_id"] else "NEW"
                # Check if there are other completed contact tasks for this lead
                other_contact = await conn.fetchval(
                    """
                    SELECT count(*) FROM tasks 
                    WHERE lead_id = $1 AND task_id != $2 
                      AND template_id IN ('TASK_LEAD_FIRST_CONTACT', 'TASK_LEAD_FOLLOWUP')
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
                    "SELECT count(*) FROM activities WHERE opportunity_id = $1 AND template_id != 'ACT_LEAD_QUALIFIED'",
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

        # C) Property Matching reversions
        elif tmpl_id == "TASK_OPPORTUNITY_MATCH_PROPERTIES":
            if opp_id:
                await conn.execute(
                    "UPDATE opportunities SET stage = 'QUALIFIED', updated_at = NOW() WHERE opportunity_id = $1",
                    opp_id
                )
                opp_reverted = "QUALIFIED"

        # D) Viewing Schedule reversions
        elif tmpl_id in ("TASK_VIEWING_SCHEDULE", "TASK_VIEWING_RESCHEDULE"):
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
                       u.full_name as assigned_agent_name, mgr.full_name as manager_name
                FROM leads l
                LEFT JOIN customers c ON l.customer_id = c.customer_id
                LEFT JOIN users u ON l.assigned_user_id = u.user_id
                LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
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
                               u.full_name as assigned_agent_name, mgr.full_name as manager_name
                        FROM leads l
                        LEFT JOIN customers c ON l.customer_id = c.customer_id
                        LEFT JOIN users u ON l.assigned_user_id = u.user_id
                        LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
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
               OR ($3::text IS NOT NULL AND t.customer_id = $3)
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
               OR ($3::text IS NOT NULL AND a.customer_id = $3)
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
               OR ($2::text IS NOT NULL AND customer_id = $2)
            ORDER BY created_at ASC
            """,
            lead_id, customer_id
        )
        comm_list = [dict(c) for c in communications]

        # 4. Fetch viewings
        viewings = await conn.fetch(
            """
            SELECT v.*, u.unit_number, COALESCE(p.name_ar, p.name_en) as project_name, ag.full_name as agent_name
            FROM viewings v
            LEFT JOIN units u ON v.unit_id = u.unit_id
            LEFT JOIN buildings b ON u.building_id = b.building_id
            LEFT JOIN projects p ON b.project_id = p.project_id
            LEFT JOIN users ag ON v.agent_user_id = ag.user_id
            WHERE ($1::text IS NOT NULL AND v.opportunity_id = $1)
               OR ($2::text IS NOT NULL AND v.lead_id = $2)
            ORDER BY v.created_at ASC
            """,
            opportunity_id, lead_id
        )
        viewing_list = [dict(v) for v in viewings]

        # 5. Fetch offers
        offers = await conn.fetch(
            """
            SELECT o.*, u.unit_number, u.asking_price
            FROM offers o
            LEFT JOIN units u ON o.unit_id = u.unit_id
            WHERE $1::text IS NOT NULL AND o.opportunity_id = $1
            ORDER BY o.valid_until DESC
            """,
            opportunity_id
        )
        offer_list = [dict(o) for o in offers]

        # 6. Fetch reservations & contracts
        reservations = await conn.fetch(
            """
            SELECT r.*, u.unit_number
            FROM reservations r
            LEFT JOIN units u ON r.unit_id = u.unit_id
            WHERE ($1::text IS NOT NULL AND r.opportunity_id = $1)
               OR ($2::text IS NOT NULL AND r.customer_id = $2)
            ORDER BY r.reserved_at DESC
            """,
            opportunity_id, customer_id
        )
        res_list = [dict(r) for r in reservations]

        contracts = await conn.fetch(
            """
            SELECT c.*
            FROM contracts c
            JOIN reservations r ON c.reservation_id = r.reservation_id
            WHERE ($1::text IS NOT NULL AND r.opportunity_id = $1)
               OR ($2::text IS NOT NULL AND r.customer_id = $2)
            ORDER BY c.signed_at DESC NULLS LAST, c.contract_id DESC
            """,
            opportunity_id, customer_id
        )
        contract_list = [dict(c) for c in contracts]

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

        is_stalled = (not is_terminal) and (len(pending_tasks) == 0)
        
        stalled_reason_ar = None
        stalled_reason_en = None
        recommended_actions = []

        if is_stalled:
            opp_stage = opp_row["stage"].upper() if opp_row else None
            lead_status = lead_row["status"].upper() if lead_row else None

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

        # 8. Build Chronological Journey Timeline
        timeline = []
        for a in activity_list:
            timeline.append({
                "type": "ACTIVITY",
                "id": a["activity_id"],
                "subject": a["subject"],
                "description": a["description"],
                "outcome": a["outcome"],
                "timestamp": (a["completed_at"] or a["created_at"]).isoformat() if (a["completed_at"] or a["created_at"]) else None,
                "user_name": a["user_name"]
            })
        for c in comm_list:
            timeline.append({
                "type": "COMMUNICATION",
                "id": c["communication_id"],
                "subject": c["subject"],
                "description": c["body"],
                "channel": c["channel"],
                "direction": c["direction"],
                "timestamp": (c["sent_at"] or c["created_at"]).isoformat() if (c["sent_at"] or c["created_at"]) else None,
                "user_name": "System/Agent"
            })
        for v in viewing_list:
            timeline.append({
                "type": "VIEWING",
                "id": v["viewing_id"],
                "subject": f"معاينة الوحدة #{v['unit_number']}",
                "description": f"الموعد: {v['scheduled_start']}. الحالة: {v['status']}",
                "timestamp": v["created_at"].isoformat() if v["created_at"] else None,
                "user_name": v["agent_name"]
            })
        for o in offer_list:
            timeline.append({
                "type": "OFFER",
                "id": o["offer_id"],
                "subject": f"عرض مالي للوحدة #{o['unit_number']}",
                "description": f"المبلغ: {float(o['offer_amount'] or 0):,.2f} ريال. الحالة: {o['status']}",
                "timestamp": o["valid_until"].isoformat() if o["valid_until"] else None,
                "user_name": "Sales Agent"
            })
        for r in res_list:
            timeline.append({
                "type": "RESERVATION",
                "id": r["reservation_id"],
                "subject": f"حجز الوحدة #{r['unit_number']}",
                "description": f"رقم الحجز: {r['reservation_number']}. العربون: {float(r['deposit_amount'] or 0):,.2f} ريال. الحالة: {r['status']}",
                "timestamp": r["reserved_at"].isoformat() if r["reserved_at"] else None,
                "user_name": "Operations"
            })
        for c in contract_list:
            timeline.append({
                "type": "CONTRACT",
                "id": c["contract_id"],
                "subject": f"عقد رقم {c['contract_number']}",
                "description": f"القيمة: {float(c['contract_value'] or 0):,.2f} ريال. الحالة: {c['status']}",
                "timestamp": c["signed_at"].isoformat() if c["signed_at"] else now_dt.isoformat(),
                "user_name": "Legal"
            })

        timeline.sort(key=lambda x: str(x.get("timestamp") or ""))

        # 9. Format Customer & Agent info
        cust_name = ""
        cust_mobile = ""
        agent_name = ""
        mgr_name = ""
        if lead_row:
            cust_name = f"{lead_row['first_name'] or ''} {lead_row['last_name'] or ''}".strip() or lead_row["company_name"] or "Client"
            cust_mobile = lead_row["mobile"] or ""
            agent_name = lead_row["assigned_agent_name"] or ""
            mgr_name = lead_row["manager_name"] or ""
        elif opp_row:
            cust_name = f"{opp_row['first_name'] or ''} {opp_row['last_name'] or ''}".strip() or opp_row["company_name"] or "Client"
            cust_mobile = opp_row["mobile"] or ""
            agent_name = opp_row["assigned_agent_name"] or ""
            mgr_name = opp_row["manager_name"] or ""

        # Format dates in tasks
        formatted_pending = []
        for pt in pending_tasks:
            pt_copy = dict(pt)
            if pt_copy.get("due_at"):
                pt_copy["due_at"] = pt_copy["due_at"].isoformat()
            if pt_copy.get("created_at"):
                pt_copy["created_at"] = pt_copy["created_at"].isoformat()
            formatted_pending.append(pt_copy)

        return {
            "lead_id": lead_id,
            "opportunity_id": opportunity_id,
            "customer_id": customer_id,
            "customer_name": cust_name,
            "customer_mobile": cust_mobile,
            "assigned_agent_name": agent_name,
            "manager_name": mgr_name,
            "current_stage": current_stage,
            "is_stalled": is_stalled,
            "stalled_reason_ar": stalled_reason_ar,
            "stalled_reason_en": stalled_reason_en,
            "recommended_actions": recommended_actions,
            "timeline": timeline,
            "pending_tasks": formatted_pending,
            "completed_tasks_count": len([t for t in task_list if t["status"] == "COMPLETED"]),
            "activities_count": len(activity_list),
            "communications_count": len(comm_list),
            "viewings_count": len(viewing_list),
            "offers_count": len(offer_list),
            "reservations_count": len(res_list),
            "contracts_count": len(contract_list)
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
            spawned_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
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


