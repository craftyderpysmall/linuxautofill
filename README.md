# LinuxAutofill

iOS-style verification autofill for Linux. A background service watches your iPhone's texts and your Gmail
inboxes. When a verification code or link arrives, it copies it to the clipboard and shows a notification.

| It finds | Click the notification to | Sources |
|---|---|---|
| A code, like `482913` or `G-482913` | Type the code into the focused window | iPhone SMS, Gmail |
| A verification link, like a "Verify My Email" button | Open the link in your browser | Gmail only |

After 60 seconds, the clipboard goes back to what you had copied before, unless you've copied something else since.
Nothing is typed or opened unless you click.

## How it works

```
iPhone text --> Shortcuts automation --HTTP POST--> http_source --+
                                                                  +--> detect --> deliver
Gmail accounts ------- checked over IMAP ---------> imap_source --+
```

- **SMS:** an automation on the iPhone forwards incoming texts to the service over your local network.
- **Gmail:** the service connects to each account with an app password and checks for new mail about every
  0.65 seconds. Mail is opened read-only, so nothing gets marked as read.
- **Detection:** this runs entirely on your computer. Only your Gmail connection and the phone's request are
  involved, and no other service sees your messages.
- **Duplicates:** the same code or link is only delivered once within 2 minutes, even if it arrives by both routes.

## Requirements

- A Wayland desktop with a notification daemon that supports actions. Built and tested on Hyprland with mako.
- Python, with no packages to install. Tested on 3.14.
- `wl-clipboard`, `libnotify` and `xdg-utils`.
- `wtype` for click-to-paste. Without it, codes are still copied, but clicking does nothing.
- `avahi`, so the iPhone can find this computer by name.
- An iPhone on the same network for SMS, and 2-Step Verification on each Gmail account.

## Setup

Run these commands from the project folder, wherever you keep it:

```sh
cd path/to/LinuxAutofill
```

### 1. Install the tools

```sh
sudo pacman -S --needed wtype avahi
```

### 2. Create the config

```sh
mkdir -p ~/.config/linuxautofill
cp config.example.toml ~/.config/linuxautofill/config.toml
chmod 600 ~/.config/linuxautofill/config.toml
```

The service won't start if other users can read this file, because it holds your secrets.

Generate a token for the iPhone and put it in `token`:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Connect Gmail

Create an app password at <https://myaccount.google.com/apppasswords>, signed in to that account. Then add it
with your full address, repeating the section for each account:

```toml
[[gmail]]
address = "first@gmail.com"
app_password = "..."

[[gmail]]
address = "second@gmail.com"
app_password = "..."
```

Use an app password, not your Google password. Spaces in it don't matter.

### 4. Let your iPhone reach this computer

Your router can give this computer a new IP address after a restart, so the automation connects by name instead.
Avahi announces that name on your network, and `ufw`'s default rules already allow its traffic:

```sh
sudo systemctl enable --now avahi-daemon
avahi-resolve -n "$(hostnamectl hostname).local"
```

The last command should print this computer's name, ending in `.local`, and its current address. You'll use that
name in step 6. If another device already has the name, Avahi adds a number, like `mypc-2.local`.
`journalctl -u avahi-daemon` shows the name it chose.

Next, find your network's range, which is the first value that this prints, like `192.168.68.0/22`:

```sh
ip -4 route show scope link
```

Then allow that range through the firewall:

```sh
sudo ufw allow from <network-range> to any port 8787 proto tcp
```

The iPhone's address can change too, even with **Private Wi-Fi Address** turned off, so this allows every device on
your network instead of just the phone. Each request still needs your token.

### 5. Start the service

```sh
mkdir -p ~/.config/systemd/user
ln -sf "$PWD/systemd/linuxautofill.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now linuxautofill
```

It now starts when you log in to Hyprland, including after a reboot, and stops when you log out.

### 6. Create the iPhone automation

On the iPhone, turn on **Shortcuts** under **Settings > Privacy & Security > Local Network**.

In the Shortcuts app, open **Automation**, tap **+**, and choose **Message**. iOS requires a filter, so leave
**Sender** empty and enter a single space in **Message Contains**. Nearly every text has a space, so one
automation catches any wording, and the service does the real detection. If iOS won't accept a space, use the
letter `o`, which misses very short texts like `PIN: 1234`.

Choose **Run Immediately**, then **New Blank Automation**, and add **Get Contents of URL**:

| Setting | Value |
|---|---|
| URL | `http://<hostname>.local:8787/message` |
| Method | POST |
| Header | `Authorization` = `Bearer <your token>` |
| Request Body | JSON |
| Field `text` (Text) | Shortcut Input |

Tap the `text` value and pick **Shortcut Input** from the bar above the keyboard, so that it appears as a blue
token. Anything you type there is sent as literal text. If the token doesn't work, tap it and set its type to
**Text**.

### 7. Test it

Watch the log, then trigger a real sign-in code by text and by email:

```sh
journalctl --user -u linuxautofill -f
```

You should see `sms: code delivered` and `mail: code delivered`. iOS may not run the automation for an iMessage
you send yourself, so use a real code.

## Using it

When a notification appears, the code or link is already on your clipboard. Paste it yourself, or click the
notification:

- **Code:** click with the input field focused, and the code is typed there.
- **Link:** the notification shows the link's domain. Check it, then click to open the link.

Real links often go through tracking domains, like `click.redditmail.com`, so an unfamiliar name isn't proof of
a scam. If you weren't expecting the email, don't click.

## Managing the service

| Task | Command |
|---|---|
| Check whether it's running | `systemctl --user status linuxautofill` |
| Restart it, after changing the config | `systemctl --user restart linuxautofill` |
| Stop it until your next login | `systemctl --user stop linuxautofill` |
| Stop it and keep it off | `systemctl --user disable --now linuxautofill` |
| Turn it back on | `systemctl --user enable --now linuxautofill` |
| Watch the log | `journalctl --user -u linuxautofill -f` |

The service finds the project through its symlink, so the folder can live anywhere. Moving it breaks the
symlink, so rerun this from the new location:

```sh
ln -sf "$PWD/systemd/linuxautofill.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user reenable linuxautofill
systemctl --user restart linuxautofill
```

To uninstall, stop it and keep it off, then delete `~/.config/systemd/user/linuxautofill.service` and
`~/.config/linuxautofill/`. Also remove the `ufw` rule, the iPhone automation, and your Gmail app passwords. If
nothing else needs Avahi, run `sudo systemctl disable --now avahi-daemon`.

## Configuration

Settings are in `~/.config/linuxautofill/config.toml`. Restart the service after changing them.

| Setting | Default | Purpose |
|---|---|---|
| `clear_after` | `60` | Seconds until the clipboard is restored and the notification closes |
| `extra_keywords` | `[]` | Words to treat as code keywords, such as other languages: `["clave", "código"]` |
| `[http] host` | `0.0.0.0` | Address to listen on |
| `[http] port` | `8787` | Port to listen on. Update the automation and `ufw` rule if you change it |
| `[http] token` | | Secret that the iPhone sends. Remove `[http]` to turn SMS off |
| `[[gmail]] address` | | Full Gmail address. Remove the section to stop watching that account |
| `[[gmail]] app_password` | | That account's app password |

You need at least one of `[http]` or `[[gmail]]`.

## What gets detected

**Codes** need a keyword, such as code, OTP, passcode, PIN, verification or login, near something shaped like a
code: 4-8 digits, `123-456`, `G-123456`, or a mix like `A1B2C3`. Letters-only codes only count directly after a
phrase like `code is`.

Prices, dates, phone numbers, web addresses, order numbers and promo codes are ignored. If it isn't clear which
value is the code, nothing happens, because a wrong guess would overwrite your clipboard.

**Links** are only checked in emails with no code. The service looks for a button labelled like
`Verify My Email`, or a link whose address or preceding words mention verifying, confirming or activating. Links
for unsubscribing, settings, help and the like are skipped. Only `http` and `https` links are used.

Links in texts are ignored, because fake "verify your account" texts are a common scam.

## Speed

Each new email logs where its time went:

```
mail: sender to Gmail 0s, Gmail to here 3s
```

| Method | Time behind Gmail's receive time |
|---|---|
| IDLE push | 10-23s |
| Polling with `STATUS` | 6-12s |
| Reopening the inbox, used now | About 3s |

These come from a small number of test emails, so treat them as rough. The remaining 3 seconds appears to be
Gmail's own processing. Any time a sender takes before Gmail has the email can't be reduced here.

## Log messages

| Log shows | Meaning |
|---|---|
| `sms: listening on port 8787` | The service started |
| `mail <address>: connected` | That Gmail account is being watched |
| `sms: code delivered` | A code arrived by text |
| `mail: code delivered`, `mail: link delivered` | A code or link arrived by email |
| `sms: duplicate skipped` or `mail: duplicate skipped` | It was already delivered in the last 2 minutes |
| `mail: no code in N character message` | That email has no code or link, which is normal for most mail |
| `sms: no code in 0 character message` | The automation's `text` field is empty |
| `sms: no code in N character message` | The text has no code, or `text` holds typed text instead of the token |
| `sms: rejected request from <ip> with 401` | The automation's token doesn't match the config |
| `mail <address>: IMAP error: ...` | Usually a wrong app password. It keeps retrying |
| `mail <address>: connection lost: ...` | The network dropped, and it reconnects by itself |
| `mail <address>: check took Ns` | Gmail or the network was slow to answer, which delays new mail by that much |
| `<source>: delivery failed: ...` | The clipboard couldn't be reached, so check that you're logged in |
| `could not read clipboard: ...` | Your previous clipboard wasn't saved, so it's cleared afterwards instead |
| `could not restore clipboard: ...` | The code or link may still be on the clipboard |

The log never contains codes, links or message text.

## Troubleshooting

**No log line appears when a text arrives, or the automation says it could not connect to the server.** The
request isn't reaching this computer. If the automation's URL uses an IP address instead of the `.local` name,
this computer may have a new address since it restarted, so switch to the name.

Otherwise, open `http://<hostname>.local:8787/` in Safari on the iPhone. An error page from the service, such as
"Unsupported method", means the network and firewall are fine, so check Local Network access and **Run
Immediately** in the automation.

If Safari can't connect, try `http://<this-computer-ip>:8787/`, using the address from `ip -4 -br addr` without
the `/22` or similar at the end. If that works, the iPhone can't find the name, which is covered next. If it
doesn't, check that the iPhone is on the same network, then run `sudo ufw status` and check that the rule's range
includes the iPhone's address, shown under **Settings > Wi-Fi > ⓘ**.

**The iPhone can't find the `.local` name.** Check that `systemctl is-active avahi-daemon` prints `active`. If it
does, your router may be blocking name lookups, which some mesh routers do. Give this computer a fixed address
instead. The simplest way is to reserve one in your router's settings. Without router access, set one here:

```sh
nmcli -t -f NAME,DEVICE connection show --active
nmcli -g IP4.GATEWAY,IP4.DNS device show <device>
nmcli connection modify <connection> ipv4.method manual ipv4.addresses <address>/<prefix> ipv4.gateway <gateway> ipv4.dns "<dns>"
nmcli connection up <connection>
```

The first two commands show your connection, device, gateway and DNS servers. Separate DNS servers with spaces in
the third command. Pick an address inside your network's range, far from those in use, because the router doesn't
know it's taken and could still give it to another device. Then use that address in the automation's URL. This only
affects that one connection. To undo it:

```sh
nmcli connection modify <connection> ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
nmcli connection up <connection>
```

**A real code wasn't detected.** Find the wording, then add a new keyword with `extra_keywords` if that's what's
missing.

**The service fails with `Unit linuxautofill.service not found`.** The symlink is broken, usually from running
`ln` outside the project folder. Rerun the commands under [Managing the service](#managing-the-service) from the
project folder.

**Clicking a code notification does nothing.** Install `wtype`, then restart the service.

## Limitations

- **SMS needs a connection to this computer.** That normally means the same network. Texts that arrive while the
  iPhone can't reach it are lost, not queued. A VPN like Tailscale would fix this: use its address for this
  computer in the automation.
- **Almost all your texts are sent to this computer.** That's a result of the broad filter. Their contents are
  discarded after checking, but they cross your Wi-Fi as plain HTTP, along with the token, so don't use this on
  shared networks without a VPN.
- **Your previous clipboard comes back in one format.** Plain text, files and images are restored, but formatted
  text comes back without its formatting. It's held in memory only, so restarting the service before the 60 seconds
  are up loses it and leaves the code on the clipboard.
- **Password managers.** Copied passwords aren't restored if the manager marks them as secret, as KeePassXC does.
  One that doesn't could have a password put back after it cleared it.
- **Gmail only.** Other email providers aren't supported.
- **Spam isn't watched.** Only the Inbox is checked.
- **Gmail may limit heavy use.** Polling makes roughly 130,000 requests a day per account. If the log fills with
  errors, raise `POLL_SECONDS` in `linuxautofill/imap_source.py`.
- **Mail older than 10 minutes is skipped.** After a long disconnection, old codes aren't delivered.
- **Do-not-disturb hides notifications.** With mako's do-not-disturb mode on, codes are still copied.
- **Anyone can send you a fake code or link.** Only click when you're expecting one.

## Development

```sh
python3 -m unittest
python3 -m linuxautofill --config path/to/config.toml
```

| File | Purpose |
|---|---|
| `linuxautofill/__main__.py` | Starts the sources and handles each message |
| `linuxautofill/detect.py` | Finds codes and links. Text handling only, with no I/O |
| `linuxautofill/imap_source.py` | Checks Gmail and reads emails |
| `linuxautofill/http_source.py` | Receives texts from the iPhone |
| `linuxautofill/deliver.py` | Handles the clipboard, notifications and clicks |
| `linuxautofill/config.py` | Loads and validates the config |
| `systemd/linuxautofill.service` | The user service |
