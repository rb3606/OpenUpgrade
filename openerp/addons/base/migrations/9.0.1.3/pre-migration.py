# -*- coding: utf-8 -*-
# Copyright Stephane LE CORNEC
# Copyright 2017 Tecnativa - Pedro M. Baeza <pedro.baeza@tecnativa.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from openupgradelib import openupgrade
from openerp.addons.openupgrade_records.lib import apriori


column_copies = {
    'ir_actions': [
        ('help', None, None),
    ],
    'ir_ui_view': [
        ('arch', 'arch_db', None),
    ],
    'res_partner': [
        ('type', None, None),
    ]
}

field_renames = [
    ('res.partner.bank', 'res_partner_bank', 'bank', 'bank_id'),
    # renamings with oldname attribute - They also need the rest of operations
    ('res.partner', 'res_partner', 'ean13', 'barcode'),
]


OBSOLETE_RULES = (
    'multi_company_default_rule',
    'res_currency_rule',
)


def remove_obsolete(cr):
    openupgrade.logged_query(cr, """
        delete from ir_rule rr
        using ir_model_data d where rr.id=d.res_id
        and d.model = 'ir.rule' and d.module = 'base'
        and d.name in {}
        """.format(OBSOLETE_RULES))


@openupgrade.logging()
def rename_utm(env):
    """Handle crm.tracking.* -> utm.* renames.

    This must be done in base because utm is a new module in v9, and crm
    depends on it. This means that utm will not execute migration scripts
    (because it's installed, not migrated), and crm migration scripts will
    have all utm data already in place.

    What we do here instead is to migrate minimal parts before utm
    is even installed.
    """
    if openupgrade.table_exists(env.cr, "crm_tracking_campaign"):
        openupgrade.rename_models(env.cr, [
            ("crm.tracking.campaign", "utm.campaign"),
            ("crm.tracking.medium", "utm.medium"),
            ("crm.tracking.source", "utm.source"),
        ])
        openupgrade.rename_tables(env.cr, [
            ("crm_tracking_campaign", "utm_campaign"),
            ("crm_tracking_medium", "utm_medium"),
            ("crm_tracking_source", "utm_source"),
        ])
        openupgrade.rename_xmlids(env.cr, [
            ("crm.crm_medium_banner", "utm.utm_medium_banner"),
            ("crm.crm_medium_direct", "utm.utm_medium_direct"),
            ("crm.crm_medium_email", "utm.utm_medium_email"),
            ("crm.crm_medium_phone", "utm.utm_medium_phone"),
            ("crm.crm_medium_website", "utm.utm_medium_website"),
            ("crm.crm_source_mailing", "utm.utm_source_mailing"),
            ("crm.crm_source_newsletter", "utm.utm_source_newsletter"),
            ("crm.crm_source_search_engine", "utm.utm_source_search_engine"),
        ])


def cleanup_modules(cr):
    """Don't report as missing these modules, as they are integrated in
    other modules."""
    openupgrade.update_module_names(
        cr, apriori.merged_modules, merge_modules=True,
    )


def map_res_partner_type(cr):
    """ The type 'default' is not an option in v9.
        By default we map it to 'contact'.
    """
    openupgrade.map_values(
        cr,
        openupgrade.get_legacy_name('type'), 'type',
        [('default', 'contact')],
        table='res_partner', write='sql')


def has_recurring_contracts(cr):
    """ Whether or not to migrate to the contract module """
    if openupgrade.column_exists(
            cr, 'account_analytic_account', 'recurring_invoices'):
        cr.execute(
            """SELECT id FROM account_analytic_account
            WHERE recurring_invoices LIMIT 1""")
        if cr.fetchone():
            return True
    return False


def migrate_translations(cr):
    """ Translations of field names are encoded differently in Odoo 9.0:
     version |           name                    | res_id |  type
    ---------+-----------------------------------+--------+-------
     8.0     | ir.module.module,summary          |      0 | field
     9.0     | ir.model.fields,field_description |    759 | model
    """
    openupgrade.logged_query(
        cr, """
        WITH mapping AS (
            SELECT imd.module,
                imf.model||','||imf.name AS name80,
                'ir.model.fields,field_description' AS name90,
                imd.res_id
            FROM ir_model_data imd
            JOIN ir_model_fields imf ON imf.id = imd.res_id
            WHERE imd.model = 'ir.model.fields' ORDER BY imd.id DESC)
        UPDATE ir_translation
        SET name = mapping.name90, type = 'model', res_id = mapping.res_id
        FROM mapping
        WHERE name = mapping.name80
            AND type = 'field'
            AND (ir_translation.module = mapping.module
                 OR ir_translation.module IS NULL); """)


def switch_noupdate_flag(cr):
    """"Some XML-IDs have changed their noupdate status, so we change it as
    well.
    """
    openupgrade.logged_query(
        cr, """
        UPDATE ir_model_data
        SET noupdate=False
        WHERE module='base' AND name IN ('group_public', 'group_portal')""",
    )


def propagate_currency_company(env):
    openupgrade.add_fields(
        env, [('company_id', 'res.currency.rate', 'res_currency_rate',
               'many2one', False, 'base')],
    )
    openupgrade.logged_query(
        env.cr, """
        UPDATE res_currency_rate rcr SET company_id = rc.company_id
        FROM res_currency rc WHERE rc.id = rcr.currency_id
        """,
    )

def run_lovefurniture(cr):
    cr.execute("update ir_values set value = 10  where name = 'taxes_id'")
    cr.execute("update ir_values set value = 11  where name = 'supplier_taxes_id'")


@openupgrade.migrate(use_env=True)
def migrate(env, version):
    cr = env.cr
    module_renames = dict(apriori.renamed_modules)
    if not has_recurring_contracts(cr):
        # Don't install contract module without any recurring invoicing
        del module_renames['account_analytic_analysis']
    openupgrade.update_module_names(
        cr, module_renames.iteritems()
    )
    openupgrade.copy_columns(cr, column_copies)
    openupgrade.rename_fields(env, field_renames, no_deep=True)
    run_lovefurniture(cr)
    remove_obsolete(cr)
    pre_create_columns(cr)
    cleanup_modules(cr)
    map_res_partner_type(cr)
    migrate_translations(env.cr)
    switch_noupdate_flag(env.cr)
    rename_utm(env)
    propagate_currency_company(env)


def pre_create_columns(cr):
    openupgrade.logged_query(cr, """
        alter table ir_model_fields add column compute text""")
