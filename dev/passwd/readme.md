# nothing to see here.

sv1 is a pass with hash.  
sv2 is a pass with hash and salt  

the MP standard method is a command that prompts for
an ascii password. 
from intrim testing, it would appear that even if sv1, sv2 passgen is in use,
the ascii pass is still able to set the security bit off temporarily.  

its been a few months since (6) since I messed with this last,  
and just wanted to make a note on this. I just want to download and upload  
zld, znv, and znx files, I couldnt give a damn about the passwd.  
Except, that if a password is previously set, and I want to program update,  
I have to unset the security bit.  
ZLD w/firmware, and ZNX w/firmware both seem to have alternate transports  
for firmware installations, though both are Maintenance Protocol driven.


I just saw the getpass library, in a testing folder, and wanted to make  
sure I dont loose track of my work on this. 



