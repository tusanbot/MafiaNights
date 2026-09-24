select cron.alter_job(
  job_id := (select jobid from cron.job where jobname = 'mafia_tick_every_second'),
  schedule := '5 seconds'
);
