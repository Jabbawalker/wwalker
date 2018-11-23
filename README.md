# wwalker

## setup

### prerequisites
* `pip3 install telethon`

### get script
*  `git clone https://github.com/xrayburster/wwalker.git`

### cfg
*  copу wwalker.cfg.dst -> wwalker.cfg `cp wwalker.cfg.dst wwalker.cfg`
* set correct API ID and hash in `[api]` section (you can get them [here](https://my.telegram.org) in API development tools)
* set stealth to `no` in `[bot]` section
* run script and complete auth (enter phonenumber and received code)
* create group chat with yourself only and type `/get_chat_id` in this chat.
  you will receive message containing chat id. set gained id as value for `ctl_chat_id` in `[bot]` section
* set `stealth` to `yes` in `[bot]` section (or remove it completely. yes is default value for option)
* restart script
* type `?` for help in ctl chat
* enjoy and wait for the deserved ban
