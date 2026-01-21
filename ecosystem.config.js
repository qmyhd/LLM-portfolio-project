// PM2 Ecosystem Configuration for Discord Bot
// 
// This configuration keeps the Discord bot running continuously on EC2.
// PM2 automatically restarts the bot if it crashes.
//
// Installation:
//   npm install -g pm2
//
// Usage:
//   pm2 start ecosystem.config.js
//   pm2 status                    # Check status
//   pm2 logs discord-bot          # View logs
//   pm2 restart discord-bot       # Restart
//   pm2 stop discord-bot          # Stop
//   pm2 save                      # Save process list
//   pm2 startup                   # Configure auto-start on boot

module.exports = {
  apps: [
    {
      name: 'discord-bot',
      script: 'python',
      args: ['-m', 'src.bot.bot'],
      cwd: '/home/ec2-user/LLM-portfolio-project',
      
      // Python interpreter (use virtual environment)
      interpreter: '/home/ec2-user/LLM-portfolio-project/.venv/bin/python',
      interpreter_args: '',
      
      // Environment
      env: {
        PYTHONPATH: '/home/ec2-user/LLM-portfolio-project',
        PYTHONUNBUFFERED: '1'
      },
      
      // Process management
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      
      // Restart behavior
      max_restarts: 10,
      min_uptime: '30s',
      restart_delay: 5000,
      
      // Logging
      log_file: '/var/log/discord-bot/combined.log',
      out_file: '/var/log/discord-bot/out.log',
      error_file: '/var/log/discord-bot/error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      
      // Graceful shutdown
      kill_timeout: 10000,
      wait_ready: true,
      listen_timeout: 10000
    }
  ]
};
