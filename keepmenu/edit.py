"""Methods for editing entries and groups

"""
import os
import random
from secrets import choice
import shlex
import string
from subprocess import call
import tempfile
from urllib import parse

import keepmenu
from keepmenu.menu import dmenu_select, dmenu_err
from keepmenu.totp import gen_otp
from keepmenu.type import type_text


def add_entry(kpo):
    """Add Keepass entry

    Args: kpo - Keepass object
    Returns: False if not added
             Keepass Entry object on success

    """
    group = select_group(kpo)
    if group is False:
        return False
    entry = kpo.add_entry(destination_group=group, title="", username="", password="")
    edit = True
    while edit is True:
        edit = edit_entry(kpo, entry)
    return entry


def delete_entry(kpo, kp_entry):
    """Delete an entry

    Args: kpo - Keepass object
          kp_entry - keepass entry
    Returns: True if no delete
             False if delete

    """
    inp = "NO\nYes - confirm delete\n"
    delete = dmenu_select(2, "Confirm delete", inp=inp)
    if delete != "Yes - confirm delete":
        return True
    kpo.delete_entry(kp_entry)
    kpo.save()
    return False


def edit_entry(kpo, kp_entry):
    # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements
    """Edit title, username, password, url and autotype sequence for an entry.

    Args: kpo - Keepass object
          kp_entry - selected Entry object

    Returns: True to continue editing
             False if done

    """
    fields = [str(f"Title: {kp_entry.title}"),
              str(f"Path: {'/'.join(kp_entry.path[:-1])}"),
              str(f"Username: {kp_entry.username}"),
              str("Password: **********") if kp_entry.password else "Password: None",
              str("TOTP: ******") if kp_entry.get_custom_property("otp") else "TOTP: None",
              str(f"Url: {kp_entry.url}"),
              "Notes: <Enter to Edit>" if kp_entry.notes else "Notes: None",
              str(f"Expiry time: {kp_entry.expiry_time}")
              if kp_entry.expires is True else "Expiry date: None",
              "Delete Entry: "]
    if hasattr(kp_entry, 'autotype_sequence') and hasattr(kp_entry, 'autotype_enabled'):
        fields[5:5] = [str(f"Autotype Sequence: {kp_entry.autotype_sequence}"),
                       str(f"Autotype Enabled: {kp_entry.autotype_enabled}")]
    inp = "\n".join(fields)
    sel = dmenu_select(len(fields), inp=inp)
    try:
        field, sel = sel.split(": ", 1)
    except (ValueError, TypeError):
        return False
    field = field.lower().replace(" ", "_")
    if field == 'password':
        sel = kp_entry.password
    edit = f"{sel}\n" if sel is not None else "\n"
    if field == 'delete_entry':
        return delete_entry(kpo, kp_entry)
    if field == 'path':
        group = select_group(kpo)
        if not group:
            return True
        kpo.move_entry(kp_entry, group)
        return True
    pw_choice = ""
    if field == 'password':
        inputs = [
            "Generate password",
            "Manually enter password",
        ]
        if kp_entry.password:
            inputs.append("Type existing password")
        pw_choice = dmenu_select(len(inputs), "Password Options", inp="\n".join(inputs))
        if pw_choice == "Manually enter password":
            pass
        elif pw_choice == "Type existing password":
            type_text(kp_entry.password)
            return False
        elif not pw_choice:
            return True
        else:
            pw_choice = ''
            length = dmenu_select(1, "Password Length?", inp="20\n")
            if not length:
                return True
            try:
                length = int(length)
            except ValueError:
                length = 20
            chars = get_password_chars()
            if chars is False:
                return True
            sel = gen_passwd(chars, length)
            if sel is False:
                dmenu_err("Number of char groups desired is more than requested pw length")
                return True
    if field == 'totp':
        edit_totp(kp_entry)
        return True
    if field == 'autotype_enabled':
        inp = "True\nFalse\n"
        at_enab = dmenu_select(2, "Autotype Enabled? True/False", inp=inp)
        if not at_enab:
            return True
        sel = not at_enab == 'False'
    if (field not in ('password', 'notes', 'path', 'autotype_enabled')) or pw_choice:
        sel = dmenu_select(1, f"{field.capitalize()}", inp=edit)
        if not sel:
            return True
        if pw_choice:
            sel_check = dmenu_select(1, f"{field.capitalize()}", inp=edit)
            if not sel_check or sel_check != sel:
                dmenu_err("Passwords do not match. No changes made.")
                return True
    elif field == 'notes':
        sel = edit_notes(kp_entry.notes)
    setattr(kp_entry, field, sel)
    return True


def edit_totp(kp_entry):  # pylint: disable=too-many-statements,too-many-branches
    """Edit TOTP generation information

    Args: kp_entry - selected Entry object

    """
    otp_url = kp_entry.get_custom_property("otp")

    if otp_url is not None:
        inputs = [
            "Enter secret key",
            "Type TOTP",
        ]
        otp_choice = dmenu_select(len(inputs), "TOTP", inp="\n".join(inputs))
    else:
        otp_choice = "Enter secret key"

    if otp_choice == "Type TOTP":
        type_text(gen_otp(otp_url))
    elif otp_choice == "Enter secret key":
        inputs = []
        if otp_url:
            parsed_otp_url = parse.urlparse(otp_url)
            query_string = parse.parse_qs(parsed_otp_url.query)
            inputs = [query_string["secret"][0]]
        secret_key = dmenu_select(1, "Secret Key?", inp="\n".join(inputs))

        if not secret_key:
            return

        for char in secret_key:
            if char.upper() not in keepmenu.SERCRET_VALID_CHARS:
                dmenu_err("Invaild character in secret key, "
                          f"valid characters are {keepmenu.SERCRET_VALID_CHARS}")
                return

        inputs = [
            "Defaut RFC 6238 token settings",
            "Steam token settings",
            "Use cusom settings"
        ]

        otp_settings_choice = dmenu_select(len(inputs), "Settings", inp="\n".join(inputs))

        if otp_settings_choice == "Defaut RFC 6238 token settings":
            algorithm_choice = "sha1"
            time_step_choice = 30
            code_size_choice = 6
        elif otp_settings_choice == "Steam token settings":
            algorithm_choice = "sha1"
            time_step_choice = 30
            code_size_choice = 5
        elif otp_settings_choice == "Use custom settings":
            inputs = ["SHA-1", "SHA-256", "SHA-512"]
            algorithm_choice = dmenu_select(len(inputs), "Algorithm", inp="\n".join(inputs))
            if not algorithm_choice:
                return
            algorithm_choice = algorithm_choice.replace("-", "").lower()

            time_step_choice = dmenu_select(1, "Time Step (sec)", inp="30\n")
            if not time_step_choice:
                return
            try:
                time_step_choice = int(time_step_choice)
            except ValueError:
                time_step_choice = 30

            code_size_choice = dmenu_select(1, "Code Size", inp="6\n")
            if not code_size_choice:
                return
            try:
                code_size_choice = int(time_step_choice)
            except ValueError:
                code_size_choice = 6

        otp_url = (f"otpauth://totp/Main:none?secret={secret_key}&period={time_step_choice}"
                   f"&digits={code_size_choice}&issuer=Main")
        if algorithm_choice != "sha1":
            otp_url += "&algorithm=" + algorithm_choice
        if otp_settings_choice == "Steam token settings":
            otp_url += "&encoder=steam"

        kp_entry.set_custom_property("otp", otp_url)


def edit_notes(note):
    """Use $EDITOR (or 'vim' if not set) to edit the notes entry

    In configuration file:
        Set 'gui_editor' for things like emacs, gvim, leafpad
        Set 'editor' for vim, emacs -nw, nano unless $EDITOR is defined
        Set 'terminal' if using a non-gui editor

    Args: note - string
    Returns: note - string

    """
    if keepmenu.CONF.has_option("database", "gui_editor"):
        editor = keepmenu.CONF.get("database", "gui_editor")
        editor = shlex.split(editor)
    else:
        if keepmenu.CONF.has_option("database", "editor"):
            editor = keepmenu.CONF.get("database", "editor")
        else:
            editor = os.environ.get('EDITOR', 'vim')
        if keepmenu.CONF.has_option("database", "terminal"):
            terminal = keepmenu.CONF.get("database", "terminal")
        else:
            terminal = "xterm"
        terminal = shlex.split(terminal)
        editor = shlex.split(editor)
        editor = terminal + ["-e"] + editor
    note = b'' if note is None else note.encode(keepmenu.ENC)
    with tempfile.NamedTemporaryFile(suffix=".tmp") as fname:
        fname.write(note)
        fname.flush()
        editor.append(fname.name)
        try:
            call(editor)
        except FileNotFoundError:
            dmenu_err("Terminal not found. Please update config.ini.")
            note = '' if not note else note.decode(keepmenu.ENC)
            return note
        fname.seek(0)
        note = fname.read()
    note = '' if not note else note.decode(keepmenu.ENC)
    return note


def gen_passwd(chars, length=20):
    """Generate password (min = # of distinct character sets picked)

    Args: chars - Dict {preset_name_1: {char_set_1: string, char_set_2: string},
                        preset_name_2: ....}
          length - int (default 20)

    Returns: password - string OR False

    """
    sets = set()
    if chars:
        sets = set(j for i in chars.values() for j in i.values())
    if length < len(sets) or not chars:
        return False
    alphabet = "".join(set("".join(j for j in i.values()) for i in chars.values()))
    # Ensure minimum of one char from each character set
    password = "".join(choice(k) for k in sets)
    password += "".join(choice(alphabet) for i in range(length - len(sets)))
    tpw = list(password)
    random.shuffle(tpw)
    return "".join(tpw)


def get_password_chars():
    """Get characters to use for password generation from defaults, config file
    and user input.

    Returns: Dict {preset_name_1: {char_set_1: string, char_set_2: string},
                   preset_name_2: ....}
    """
    chars = {"upper": string.ascii_uppercase,
             "lower": string.ascii_lowercase,
             "digits": string.digits,
             "punctuation": string.punctuation}
    presets = {}
    presets["Letters+Digits+Punctuation"] = chars
    presets["Letters+Digits"] = {k: chars[k] for k in ("upper", "lower", "digits")}
    presets["Letters"] = {k: chars[k] for k in ("upper", "lower")}
    presets["Digits"] = {k: chars[k] for k in ("digits",)}
    if keepmenu.CONF.has_section('password_chars'):
        pw_chars = dict(keepmenu.CONF.items('password_chars'))
        chars.update(pw_chars)
        for key, val in pw_chars.items():
            presets[key.title()] = {k: chars[k] for k in (key,)}
    if keepmenu.CONF.has_section('password_char_presets'):
        if keepmenu.CONF.options('password_char_presets'):
            presets = {}
        for name, val in keepmenu.CONF.items('password_char_presets'):
            try:
                presets[name.title()] = {k: chars[k] for k in shlex.split(val)}
            except KeyError:
                print(f"Error: Unknown value in preset {name}. Ignoring.")
                continue
    inp = "\n".join(presets)
    char_sel = dmenu_select(len(presets),
                            "Pick character set(s) to use", inp=inp)
    # This dictionary return also handles Rofi multiple select
    return {k: presets[k] for k in char_sel.split('\n')} if char_sel else False


def select_group(kpo, prompt="Groups"):
    """Select which group for an entry

    Args: kpo - Keepass object
          options - list of menu options for groups

    Returns: False for no entry
             group - string

    """
    groups = kpo.groups
    num_align = len(str(len(groups)))
    pattern = str("{:>{na}} - {}")
    inp = str("\n").join([pattern.format(j, "/".join(i.path), na=num_align)
                         for j, i in enumerate(groups)])
    sel = dmenu_select(min(keepmenu.MAX_LEN, len(groups)), prompt, inp=inp)
    if not sel:
        return False
    try:
        return groups[int(sel.split('-', 1)[0])]
    except (ValueError, TypeError):
        return False


def manage_groups(kpo):
    """Rename, create, move or delete groups

    Args: kpo - Keepass object
    Returns: Group object or False

    """
    edit = True
    options = ['Create',
               'Move',
               'Rename',
               'Delete']
    group = False
    while edit is True:
        inp = "\n".join(i for i in options) + "\n\n" + \
            "\n".join("/".join(i.path) for i in kpo.groups)
        sel = dmenu_select(len(options) + len(kpo.groups) + 1, "Groups", inp=inp)
        if not sel:
            edit = False
        elif sel == 'Create':
            group = create_group(kpo)
        elif sel == 'Move':
            group = move_group(kpo)
        elif sel == 'Rename':
            group = rename_group(kpo)
        elif sel == 'Delete':
            group = delete_group(kpo)
        else:
            edit = False
    return group


def create_group(kpo):
    """Create new group

    Args: kpo - Keepass object
    Returns: Group object or False

    """
    parentgroup = select_group(kpo, prompt="Select parent group")
    if not parentgroup:
        return False
    name = dmenu_select(1, "Group name")
    if not name:
        return False
    group = kpo.add_group(parentgroup, name)
    kpo.save()
    return group


def delete_group(kpo):
    """Delete a group

    Args: kpo - Keepass object
    Returns: Group object or False

    """
    group = select_group(kpo, prompt="Delete Group:")
    if not group:
        return False
    inp = "NO\nYes - confirm delete\n"
    delete = dmenu_select(2, "Confirm delete", inp=inp)
    if delete != "Yes - confirm delete":
        return True
    kpo.delete_group(group)
    kpo.save()
    return group


def move_group(kpo):
    """Move group

    Args: kpo - Keepass object
    Returns: Group object or False

    """
    group = select_group(kpo, prompt="Select group to move")
    if not group:
        return False
    destgroup = select_group(kpo, prompt="Select destination group")
    if not destgroup:
        return False
    group = kpo.move_group(group, destgroup)
    kpo.save()
    return group


def rename_group(kpo):
    """Rename group

    Args: kpo - Keepass object
    Returns: Group object or False

    """
    group = select_group(kpo, prompt="Select group to rename")
    if not group:
        return False
    name = dmenu_select(1, "New group name", inp=group.name)
    if not name:
        return False
    group.name = name
    kpo.save()
    return group
