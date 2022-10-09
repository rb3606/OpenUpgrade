# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    This migration script copyright (C) 2012-2013 Therp BV (<http://therp.nl>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

# Maybe: investigate impact of 'model' field on ir.translation
# Ignored: removal of integer_big which openerp 6.1 claims is currently unused

from openupgrade import openupgrade
from openerp.addons.openupgrade_records.lib import apriori
from datetime import datetime

obsolete_modules = (
    'base_tools',
    'base_contact',
    'web_process',
    'web_mobile',
    'web_dashboard',
    'fetchmail_crm_claim',
    'fetchmail_crm',
    'fetchmail_hr_recruitment',
)

column_renames = {
    # login_date: field type changed as well, but
    # orm can map timestamp fields to date field
    'res_users': [
        ('date', 'login_date'),
        ('user_email', None),
        ],
    'res_company': [
        ('logo', None),
    ]
}

table_renames = [
    ('res_partner_category_rel', 'res_partner_res_partner_category_rel'),
]

xmlid_renames = [
    ('base.VEB', 'base.VUB'),
]
model_renames = [
    ('ir.actions.url', 'ir.actions.act_url'),
    ]


def disable_demo_data(cr):
    """ Disables the renewed loading of demo data """
    openupgrade.logged_query(
        cr,
        "UPDATE ir_module_module SET demo = false")


def migrate_ir_attachment(cr):
    # Data is now stored in db_datas column and datas is a function field
    # like in the document module in 6.1. If the db_datas column already
    # exist, presume that this module was installed and do nothing.
    if not openupgrade.column_exists(cr, 'ir_attachment', 'db_datas'):
        openupgrade.rename_columns(
            cr, {'ir_attachment': [('datas', 'db_datas')]})


def update_base_sql(cr):
    """
    Inject snippets of openerp/addons/base/base.sql, needed
    to upgrade the base module.

    Also check existing inheritance of ir_act_client on ir_actions.
    For ir_act_client to inherit ir_actions at table level
    is not new in 7.0, but this was not taken care of properly in
    OpenUpgrade 6.1 for a long time, so we do it again here.
    This will fix up databases that were migrated earlier on.
    """

    cr.execute("""
CREATE TABLE ir_model_constraint (
    id serial NOT NULL,
    create_uid integer,
    create_date timestamp without time zone,
    write_date timestamp without time zone,
    write_uid integer,
    date_init timestamp without time zone,
    date_update timestamp without time zone,
    module integer NOT NULL references ir_module_module on delete restrict,
    model integer NOT NULL references ir_model on delete restrict,
    type character varying(1) NOT NULL,
    name character varying(128) NOT NULL
);
CREATE TABLE ir_model_relation (
    id serial NOT NULL,
    create_uid integer,
    create_date timestamp without time zone,
    write_date timestamp without time zone,
    write_uid integer,
    date_init timestamp without time zone,
    date_update timestamp without time zone,
    module integer NOT NULL references ir_module_module on delete restrict,
    model integer NOT NULL references ir_model on delete restrict,
    name character varying(128) NOT NULL
);
""")

    cr.execute(
        """
        SELECT count(*) from pg_catalog.pg_inherits
        WHERE inhrelid = 'public.ir_act_client'::regclass::oid
        AND inhparent = 'public.ir_actions'::regclass::oid
        """)
    res = cr.fetchone()
    if not res[0]:
        cr.execute(
            "ALTER TABLE ir_act_client INHERIT ir_actions")


def create_users_partner(cr):
    """
    Users now have an inherits on res.partner.
    Transferred fields include lang, tz and email
    but these fields do not exist on the partner table
    at this point. We'll pick this up in the post
    script.

    If other modules define defaults on the partner
    model, their migration scripts should put them
    into place for these entries.

    If other modules set additional columns to
    required, the following will break. We may
    want to have a look at disabling triggers
    at that point,

    We'll create both the partner column and a custom column
    to track the partners we create here. These are not necessarily
    the same, especially if you have a custom module implementing
    similar behaviour for 6.1.
    """
    if not openupgrade.column_exists(
            cr, 'res_users', 'partner_id'):
        cr.execute(
            "ALTER TABLE res_users "
            "ADD column partner_id "
            " INTEGER")
        cr.execute(
            "ALTER TABLE res_users ADD FOREIGN KEY "
            "(partner_id) "
            "REFERENCES res_partner ON DELETE RESTRICT")
    cr.execute(
        "ALTER TABLE res_users "
        "ADD column openupgrade_7_created_partner_id "
        " INTEGER")
    cr.execute(
        "ALTER TABLE res_users ADD FOREIGN KEY "
        "(openupgrade_7_created_partner_id) "
        "REFERENCES res_partner ON DELETE SET NULL")
    cr.execute(
        "SELECT res_id FROM ir_model_data "
        "WHERE module='base' and name='user_root'")
    user_root = cr.fetchone()
    user_root_id = user_root and user_root[0] or 0
    warning_installed = openupgrade.is_module_installed(cr, 'warning')
    cr.execute(
        "SELECT id, name, active FROM res_users "
        "WHERE partner_id IS NULL")
    sql_insert_partner = (
        "INSERT INTO res_partner "
        "(name, active) "
        "VALUES(%s,%s) RETURNING id")
    if warning_installed:
        sql_insert_partner = (
            "INSERT INTO res_partner "
            "(name, active,picking_warn,sale_warn,"
            "invoice_warn,purchase_warn) "
            "VALUES("
            "%s,%s,'no-message','no-message','no-message','no-message') "
            "RETURNING id")
    for row in cr.fetchall():
        cr.execute(sql_insert_partner, row[1:])
        partner_id = cr.fetchone()[0]
        cr.execute(
            "UPDATE res_users "
            "SET partner_id = %s, "
            "openupgrade_7_created_partner_id = %s "
            "WHERE id = %s", (partner_id, partner_id, row[0]))
        if row[0] == user_root_id:
            # Insert XML ID so that the partner for the admin user
            # does not get created again when loading the data
            cr.execute(
                "INSERT INTO ir_model_data "
                "(res_id, model, module, name, noupdate) "
                "VALUES(%s, 'res.partner', 'base', 'partner_root', TRUE) ",
                (partner_id,))


def remove_obsolete_modules(cr, obsolete_modules):
    cr.execute(
        """
        UPDATE ir_module_module
        SET state = 'to remove'
        WHERE name in %s AND state <> 'uninstalled'
        """, (obsolete_modules,))

def run_lovefurniture(cr):
    #delete view
    cr.execute("delete from ir_ui_view_sc where user_id not in (select id from res_users)")
    cr.execute("delete  from ir_ui_view_sc where res_id = 108 and user_id = 1")
    
    #migrating all missing res.users reference to 1 
    qry = "select model,name from ir_model_fields where ttype ='many2one' and relation = 'res.users'  and replace(model,'.','_') in ( SELECT tablename FROM pg_catalog.pg_tables) and name in (SELECT column_name  FROM information_schema.columns WHERE table_name=replace(model,'.','_') and column_name=name)" 
    cr.execute(qry)
    for row in cr.fetchall():
        model = row[0].replace('.','_')
        name = row[1]
        query = "select id,%s from  %s where %s not in (select id from res_users)" %(name,model,name)
        cr.execute(query)
        for res in cr.fetchall():
            qr  = "UPDATE %s SET %s = 1 WHERE id = %s" %(model,name,res[0])
            cr.execute(qr)

    #Template not exist so just set blank
    qm = "update mail_compose_message set template_id = null , use_template = false  where template_id not in (select id from email_template)"
    cr.execute(qm)

    #migrating all missing res.partner to new partner
    qry = "select model,name from ir_model_fields where ttype ='many2one' and relation = 'res.partner'  and replace(model,'.','_') in ( SELECT tablename FROM pg_catalog.pg_tables) and name in (SELECT column_name  FROM information_schema.columns WHERE table_name=replace(model,'.','_') and column_name=name)" 
    cr.execute(qry)
    new_partners = {}
    for row in cr.fetchall():
        model = row[0].replace('.','_')
        name = row[1]
        query = "select id,%s from  %s where %s not in (select id from res_partner)" %(name,model,name)
        cr.execute(query)
        for res in cr.fetchall():
            if not new_partners.get(res[0]):
                qr = "INSERT INTO res_partner (name,company_id,create_date) values (%s,'%s',%s,'%s')" %(res[0],1,datetime.now())
                cr.execute(qr)
                cr.execute("select id from res_partner order by id desc limit 1")
                new_partners[res[0]] = cr.fetchone()[0]
            qr  = "UPDATE stock_move SET partner_id = %s WHERE partner_id = %s" %(new_partners.get(res[0]),res[0])
            cr.execute(qr)
                

@openupgrade.migrate()
def migrate(cr, version):
    run_lovefurniture(cr)
    disable_demo_data(cr)
    update_base_sql(cr)
    openupgrade.update_module_names(
        cr, apriori.renamed_modules.iteritems()
    )
    openupgrade.drop_columns(cr, [('ir_actions_todo', 'action_id')])
    openupgrade.rename_columns(cr, column_renames)
    openupgrade.rename_tables(cr, table_renames)
    openupgrade.rename_xmlids(cr, xmlid_renames)
    openupgrade.rename_models(cr, model_renames)
    migrate_ir_attachment(cr)
    create_users_partner(cr)
    remove_obsolete_modules(cr, obsolete_modules)
