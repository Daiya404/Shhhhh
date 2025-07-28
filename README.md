# Discord Bot Setup Guide

## Features

✅ **Coin Flip** - `/coinflip` command for heads or tails  
✅ **Custom Dice Rolling** - `/roll` command with dice notation (1d6, 2d20, etc.)  
✅ **Message Clearing** - `/clear` command that clears messages up to a replied message  
✅ **Word Blocking** - `/blockword` command to block specific words for specific users  
✅ **Custom Role Systems** - Create selectable role systems with `/createrole`  
✅ **Personal Custom Roles** - Users can create their own colored roles with `/customrole`  

## Installation

### 1. Install Python Requirements
```bash
pip install -r requirements.txt
```

### 2. Create Discord Bot
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and bot
3. Copy the bot token
4. Enable the following intents:
   - Message Content Intent
   - Server Members Intent

### 3. Bot Permissions
Your bot needs these permissions:
- Send Messages
- Use Slash Commands
- Manage Messages (for `/clear` command)
- Manage Roles (for custom role systems)
- Read Message History

### 4. Setup Bot Token
Replace `'YOUR_BOT_TOKEN'` in `main.py` with your actual bot token:
```python
await bot.start('YOUR_ACTUAL_BOT_TOKEN_HERE')
```

### 5. File Structure
Make sure your project has this structure:
```
Tika/
├── main.py
├── requirements.txt
├── README.md
├── cogs/
│   ├── __init__.py
│   ├── fun_commands.py
│   ├── moderation.py
│   ├── word_blocker.py
│   └── custom_roles.py
└── data/
    ├── blocked_words.json (created automatically)
    └── custom_roles.json (created automatically)
```

**Important:** Create an empty `__init__.py` file in the `cogs/` folder!

### 6. Run the Bot
```bash
python main.py
```

## Commands

### Fun Commands
- `/coinflip` - Flip a coin (heads or tails)
- `/roll <dice>` - Roll dice using standard notation
  - Examples: `/roll 1d6`, `/roll 2d20`, `/roll 3d8`

### Moderation Commands
- `/clear` - Clear messages up to the replied message (requires Manage Messages permission)

### Word Blocking Commands (Admin Only)
- `/blockword <user> <word>` - Block a word for a specific user
- `/unblockword <user> <word>` - Unblock a word for a specific user  
- `/listblockedwords <user>` - List blocked words for a user

### Custom Role Commands
- `/createrole <name> <description> <roles>` - Create a role system (Admin only)
  - Example: `/createrole "Game Roles" "Choose your game roles" "Valorant, Minecraft, Overwatch"`
- `/selectrole <system>` - Select roles from a system
- `/listroles` - List all role systems
- `/deleteroles <system>` - Delete a role system (Admin only)

## Usage Examples

### Creating Personal Custom Roles
```
/customrole name:"VIP Member" color:"#gold"
/customrole name:"Cool User" color:"#00ff88"
/mycustomrole                    # View your role info
/deletecustomrole               # Remove your custom role
```

### Creating a Role System
```
/createrole name:"Game Preferences" description:"Pick your favorite games" roles:"Valorant, Minecraft, Overwatch, League of Legends"
```

### Rolling Dice
```
/roll 1d20    # Roll a 20-sided die
/roll 3d6     # Roll three 6-sided dice
/roll 2d10    # Roll two 10-sided dice
```

### Blocking Words
```
/blockword user:@username word:"badword"
/listblockedwords user:@username
/unblockword user:@username word:"badword"
```

### Clearing Messages
1. Reply to a message
2. Use `/clear` command
3. All messages after the replied message will be deleted

## Special Features

### Personal Custom Roles
- **Anyone can create:** Users can create their own custom colored role
- **Auto-positioning:** Custom roles are automatically placed above role ID `1376473014559834132`
- **Color customization:** Support for hex colors (e.g., #ff0000, #00ff88)
- **No permissions:** Custom roles have no special permissions, just for display and pings
- **One per user:** Each user can have only one personal custom role at a time
- **Easy management:** Users can update, view, or delete their own roles

### Role Positioning
The bot automatically places personal custom roles above the role with ID `1376473014559834132`. If this role doesn't exist, custom roles will be placed at position 1 (above @everyone).

## Data Storage

- Blocked words are stored in `data/blocked_words.json`
- Custom role systems are stored in `data/custom_roles.json`
- Personal custom roles are stored in `data/user_custom_roles.json`
- Data persists between bot restarts

## Troubleshooting

### Common Issues

1. **Bot not responding to commands**
   - Make sure Message Content Intent is enabled
   - Verify bot has necessary permissions

2. **Slash commands not appearing**
   - Wait a few minutes after starting the bot
   - Commands sync automatically on startup

3. **Role commands not working**
   - Ensure bot has "Manage Roles" permission
   - Bot's role must be higher than roles it's trying to manage

4. **Clear command not working**
   - Bot needs "Manage Messages" permission
   - Command must be used as a reply to another message

### Permission Issues
If you get permission errors, make sure your bot has the required permissions in the server settings and that the bot's role is positioned correctly in the role hierarchy.

## Support

If you encounter any issues:
1. Check the console for error messages
2. Verify all permissions are set correctly
3. Ensure the bot token is correct and valid
4. Make sure all required files are in place