# wwalker

## setup Python Win

Download **Python3** (last version) for Windows(32\64), from [**link**](https://www.activestate.com/products/activepython/downloads/):

![Choose Version](https://github.com/Jabbawalker/wwalker/blob/master/PythonChooseVersion.png)

Now find and Install downloaded file:
* Choose Typical Installation

![Choose Typical](https://github.com/wwfix/wwalker/blob/master/PythonTypical.png)

* These boxes must be checked

![Check this box](https://github.com/wwfix/wwalker/blob/master/PythonChecked.png)

Finish Installation.
    
### prerequisites
* `pip3 install telethon`

### obtaning script
*  `git clone https://github.com/xrayburster/wwalker.git`

### cfg
*  copу wwalker.cfg.dst -> wwalker.cfg `cp wwalker.cfg.dst wwalker.cfg`
* set correct API ID and hash in `[api]` section (you can get them [here](https://my.telegram.org) in API development tools)
* run script and complete auth (enter phonenumber and received code)
* create group chat with yourself only and type `/id` in this chat.
  you will see in logs message containing chat id. set gained id as value for `ctl_chat_id` in `[bot]` section
* restart script
* type `?` for help in ctl chat
* enjoy and wait for the deserved ban
