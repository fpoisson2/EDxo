from utilitaires.scheduler_instance import start_scheduler, schedule_backup

def on_starting(server):
    schedule_backup(server.app)
    start_scheduler()