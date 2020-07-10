# OctoPrint-Mattacloud

<p align="center">
    <img src="extras/images/mattacloud.png" alt="Mattacloud by Mattalabs">
    <br/>
    <i>Add automatic error detection and remote access for your 3D printer.</i>
    <br/>
</p>

Automatic and intelligent error detection and process monitoring for your OctoPrint-enabled 3D printer, with full remote control, management and access from anywhere. Additionally, receive notifications and updates via your chosen communication medium, alerting you of failures and keeping you updated on the state of the 3D print. Overview your print history and gain insights into filament use, print times and your printer reliability.

Learn more about **Mattacloud** and its features - [https://mattalabs.com/products/mattacloud/](https://mattalabs.com/products/mattacloud/)

### Error detection and process monitoring

3D printers are not the most reliable of machines. All of us have suffered from errors whilst printing and many users find themselves _handcuffed_ to their printers, having to constantly check the printer every 5 minutes to make sure that the print is _still_ okay! If this sounds familiar to you... hopefully this plugin will help.

Numerous computer vision techniques are used to determine if an error has occurred during your 3D print. Using a mixture of machine learning, 3D printing heuristics and the direct comparison of g-code to the current state of the 3D print, an errors are reliably determined in an image of the print.

Errors that are currently detected reliably:

- Detatchment from print bed
- Offset
- Warping
- Poor bed adhesion
- Spaghetti
- Blocked extruder / out of filament
- Hotend too close to print bed

### Remote control and management

Access your 3D printer from anywhere in the world (provided that there is an internet connection...) via the OctoPrint-Mattacloud Plugin.

At present, the plugin enables you to do the following:

- View and update hotend, bed and chamber temperatures
- Control and home X, Y and Z axes
- Select prints to retrieve information
- Start, cancel, pause, resume and restart 3D prints
- Upload g-code files remotely to your printer for printing
- Delete g-code files remotely
- Receive the latest images/snapshots from your printer
- See your prints progress (time remaining and percentage completion)

### Notifications and updates

<p align="center">
    <img src="extras/images/communication.png" alt="Mattacloud - Communication">
    <br/>
    <i>Keep informed by receiving notifications and updates from the <b>mattacloud</b> to your device.</i>
    <br/>
</p>

By installing this plugin and linking a printer to your **mattacloud** account, you can receive useful notifications and updates concerning your 3D printer via various channels. When an error occurs during the 3D printing process, you will receive an alert with an attached image showing the error in addition to current progress, material usage and other useful statistics; you can then deside to take action. Additionally, you can also set up other checkpoints to receive notifications, such as upon object completion, or when a print has reached the half way mark. 

The communication channels which are currently supported are:

- Email
- SMS (Beta)
- WhatsApp (Beta)
- Facebook Messenger (Beta)

## Plugin Installation

Install via the bundled [OctoPrint Plugin Manager](https://github.com/foosel/OctoPrint/wiki/Plugin:-Plugin-Manager)
or manually using this URL:

    https://github.com/dougbrion/OctoPrint-Mattacloud/archive/master.zip

After downloading the zip file of the latest release, install it using the OctoPrint Plugin Manager.

## Setup

The setup progress takes less than 5 minutes and consists of 5 simple steps. If you follow these, all the benefits of **Mattacloud** will apply to your printer. Happy printing!

1. Join the **Mattacloud** free trial ([here](https://cloud.mattalabs.com/accounts/signup/)) or https://cloud.mattalabs.com/accounts/signup/if you already have, just [login](https://cloud.mattalabs.com/accounts/login/). (Free trial lasts for the duration of beta testing.)
2. Select your membership type - at this stage it is recommended to choose the free beta membership.
3. Add a printer to your **Mattacloud** by following the wizard and setup guide.
4. After installing the OctoPrint-Mattacloud Plugin on your OctoPrint enabled device, copy the authentication token from your newly created printer on the **Mattacloud** into the authentication token input box presented in the OctoPrint-Mattacloud Plugin tab. You can see all of your printers and their respective tokens [here](https://cloud.mattalabs.com/printer-dashboard/).
5. Test your token using the _Test Token_ button adjacent to the input box.

## Report problems

If something does not appear to be working correctly and you think you may have found a bug in the OctoPrint-Mattacloud Plugin, please create an issue on the official page [here](https://github.com/dougbrion/OctoPrint-Mattacloud/issues). In this way your issue can be understood and fixed quickly.

## Data

## License

View the [OctoPrint-Mattacloud plugin license](https://github.com/dougbrion/OctoPrint-Mattacloud/blob/master/LICENSE)
