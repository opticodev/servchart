from django.db import migrations


def reset_agent_hosts(apps, schema_editor):
    """Only the hub's own collector record (token hint "local") is local.

    0.3.0 let admins tick "Is local" on agent hosts in the Django admin, which made the
    hub's collector write its own snapshot into one of them.
    """
    Host = apps.get_model("inventory", "Host")
    Host.objects.filter(is_local=True).exclude(token_hint="local").update(is_local=False)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0002_sitesettings_logrequest_auditevent")]
    operations = [migrations.RunPython(reset_agent_hosts, migrations.RunPython.noop)]
