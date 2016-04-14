#!/usr/bin/python

# Copyright (c) 2015 Carmine Noviello
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import print_function

version = 0.2

import os
import argparse
import copy
import logging
import shutil
import re
from lxml import etree

class CubeMXImporter(object):
    """docstring for CubeMXImporter"""
    def __init__(self):
        super(CubeMXImporter, self).__init__()
        
        self.eclipseprojectpath = ""
        self.dryrun = 0
        self.logger = logging.getLogger(__name__)
        self.HAL_TYPE = None

    def setCubeMXProjectPath(self, path):
        """Set the path of CubeMX generated project folder"""

        if os.path.exists(os.path.join(path, ".mxproject")): 
            if os.path.exists(os.path.join(path, "SW4STM32")):  #For CubeMX < 4.14
                self.cubemxprojectpath = path
                self.sw4stm32projectpath = os.path.join(path, "SW4STM32")
                self.detectHALInfo()
            elif os.path.exists(os.path.join(path, ".cproject")):
                #Recent releases of CubeMX (from 4.14 and higher) allow to generate the
                #SW4STM32 project in the root folder. This means that project files are 
                #stored in the root of the CubeMX project, but this is the 
                #same behavior for TrueSTUDIO project. So we need to check if the project
                #is generated for the SW4STM32 toolchain by playing with the content of .cproject file

                if open(os.path.join(path, ".cproject")).read().find("ac6") < 0: #It is not an AC6 project
                    raise InvalidSW4STM32Project("The generated CubeMX project is not for SW4STM32 tool-chain. Please, regenerate the project again.")
                else:
                    self.cubemxprojectpath = path
                    self.sw4stm32projectpath = path
                    self.detectHALInfo()

            else:
                raise InvalidSW4STM32Project("The generated CubeMX project is not for SW4STM32 tool-chain. Please, regenerate the project again.")
        else:
            raise InvalidCubeMXFolder("The folder '%s' doesn't seem a CubeMX project" % path)
            
    def getCubeMXProjectPath(self):
        """Retrieve the path of CubeMX generated project folder"""        
        return self.cubemxprojectpath
        
    cubeMXProjectPath = property(getCubeMXProjectPath, setCubeMXProjectPath)


    def setEclipseProjectPath(self, path):
        """Set the path of Eclipse generated project folder"""

        if os.path.exists(os.path.join(path, ".cproject")):
            self.eclipseprojectpath = path
        else:
            raise InvalidEclipseFolder("The folder '%s' doesn't seem an Eclipse project" % path)
            
    def getEclipseProjectPath(self):
        """Retrieve the path of Eclipse generated project folder"""        
        return self.eclipseprojectpath
        
    eclipseProjectPath = property(getEclipseProjectPath, setEclipseProjectPath)
        
    def __addOptionValuesToProject(self, values, section, quote=True):
        if self.dryrun: return
        """Add a list of option values into a given section in the Eclipse project file"""
        options = self.projectRoot.xpath("//option[@superClass='%s']" % section) #Uses XPATH to retrieve the 'section'
        optionsValues = [o.attrib["value"] for o in options[0]] #List all available values to avoid reinsert again the same value
        for opt in options:
            for v in values:
                pattern = '"%s"' if quote else '%s' #The way how include paths and macros are stored differs. Include paths are quoted with ""
                if pattern % v not in optionsValues: #Avoid to place the same include again
                    listOptionValue = copy.deepcopy(opt[0])
                    if quote:
                        listOptionValue.attrib["value"] = "&quot;%s&quot;" % v #Quote the path
                    else:
                        listOptionValue.attrib["value"] = "%s" % v
                    opt.append(listOptionValue)

    def addAssemblerIncludes(self, includes):
        """Add a list of include paths to the Assembler section in project settings"""
        self.__addOptionValuesToProject(includes, "ilg.gnuarmeclipse.managedbuild.cross.option.assembler.include.paths")

    def addCIncludes(self, includes):
        """Add a list of include paths to the C section in project settings"""
        self.__addOptionValuesToProject(includes, "ilg.gnuarmeclipse.managedbuild.cross.option.c.compiler.include.paths")

    def addCPPIncludes(self, includes):
        """Add a list of include paths to the CPP section in project settings"""
        self.__addOptionValuesToProject(includes, "ilg.gnuarmeclipse.managedbuild.cross.option.cpp.compiler.include.paths")


    def addAssemblerMacros(self, macros):
        """Add a list of macros to the CPP section in project settings"""
        self.__addOptionValuesToProject(macros, "ilg.gnuarmeclipse.managedbuild.cross.option.assembler.defs", False)

    def addCMacros(self, macros):
        """Add a list of macros to the CPP section in project settings"""
        self.__addOptionValuesToProject(macros, "ilg.gnuarmeclipse.managedbuild.cross.option.c.compiler.defs", False)
                        
    def addCPPMacros(self, macros):
        """Add a list of macros to the CPP section in project settings"""
        self.__addOptionValuesToProject(macros, "ilg.gnuarmeclipse.managedbuild.cross.option.cpp.compiler.defs", False)

    def addSourceEntries(self, entries):
        """Add a list of directory to the source entries list in the eclipse project"""
        sources = self.projectRoot.xpath("//sourceEntries") #Uses XPATH to retrieve the 'section'
        for source in sources:
            for e in entries:
                logging.debug("Adding '%s' folder to source entries" % e)
                entry = copy.deepcopy(source[0])
                entry.attrib["name"] = e
                source.append(entry)

    def copyTree(self, src, dst, ignore=None):
        """Copy 'src' directory in 'dst' folder"""
        logging.debug("Copying folder '%s' to '%s'" % (src, dst))

        if not self.dryrun:
            shutil.copytree(src, dst, ignore)

    def copyTreeContent(self, src, dst):
        """Copy all files contsined in 'src' folder to 'dst' folder"""
        files = os.listdir(src)
        for f in files:
            fileToCopy = os.path.join(src, f)
            if os.path.isfile(fileToCopy):
                logging.debug("Copying %s to %s" % (fileToCopy, dst))
                if not self.dryrun:
                    shutil.copyfile(fileToCopy, os.path.join(dst, f))
            elif os.path.isdir(fileToCopy):
                logging.debug("Copying folder %s to %s" % (fileToCopy, dst))
                if not self.dryrun:
                    shutil.copytree(fileToCopy, os.path.join(dst, f))

    def deleteOriginalEclipseProjectFiles(self):
        """Deletes useless files generated by the GNU ARM Eclipse plugin"""
        
        dirs = ["src", "include", "system/src/cmsis", "system/src/stm32%sxx" % self.HAL_TYPE.lower(), "system/include/stm32%sxx" % self.HAL_TYPE.lower()]

        [self.deleteTreeContent(os.path.join(self.eclipseprojectpath, d)) for d in dirs]

        files = ["system/include/cmsis/stm32%sxx.h" % self.HAL_TYPE.lower(), "system/include/cmsis/system_stm32%sxx.h" % self.HAL_TYPE.lower()]
        
        try:
            if not self.dryrun:
                [os.unlink(os.path.join(self.eclipseprojectpath, f)) for f in files]
        except OSError:
            pass

        self.logger.info("Deleted uneeded files generated by GNU Eclipse plugin")

    def deleteTreeContent(self, tree):
        """Delete all files contained in a given folder"""
        for f in os.listdir(tree):
            f = os.path.join(tree, f)
            logging.debug("Deleting %s" % f)
            if not self.dryrun:
                if os.path.isfile(f):
                    os.unlink(f)
                elif os.path.isdir(f):
                    shutil.rmtree(f)

    def detectHALInfo(self):
        """Scans the SW4STM32 project file looking for relevant informations about MCU and HAL types"""

        root = None

        for rootdir, dirs, files in os.walk(self.sw4stm32projectpath):
            if ".cproject" in files:
                root = etree.fromstring(open(os.path.join(rootdir, ".cproject")).read().encode('UTF-8'))

        if root is None:
            raise InvalidSW4STM32Project("The generated CubeMX project is not for SW4STM32 tool-chain. Please, regenerate the project again.")

        options = root.xpath("//option[@superClass='gnu.c.compiler.option.preprocessor.def.symbols']")[0]

        for opt in options:
            if "STM32" in opt.attrib["value"]:
                self.HAL_MCU_TYPE = opt.attrib["value"]
                self.HAL_TYPE = re.search("([FL][0-9])", self.HAL_MCU_TYPE).group(1)
                self.logger.info("Detected MCU type: %s" % self.HAL_MCU_TYPE)
                self.logger.info("Detected HAL type: %s" % self.HAL_TYPE)

    def getAC6Includes(self):
        root = None

        for rootdir, dirs, files in os.walk(self.sw4stm32projectpath):
            if ".cproject" in files:
                root = etree.fromstring(open(os.path.join(rootdir, ".cproject")).read().encode('UTF-8'))

        if root is None:
            raise InvalidSW4STM32Project("The generated CubeMX project is not for SW4STM32 tool-chain. Please, regenerate the project again.")

        options = root.xpath("//option[@superClass='gnu.c.compiler.option.include.paths']")[0]

        return [opt.attrib["value"] for opt in options]

    def importApplication(self):
        """Import generated application code inside the Eclipse project"""
        srcIncludeDir = os.path.join(self.cubemxprojectpath, "Inc")
        srcSourceDir = os.path.join(self.cubemxprojectpath, "Src")
        dstIncludeDir = os.path.join(self.eclipseprojectpath, "include")
        dstSourceDir = os.path.join(self.eclipseprojectpath, "src")

        locations = ((srcIncludeDir, dstIncludeDir), (srcSourceDir, dstSourceDir))

        for loc in locations:
            self.copyTreeContent(loc[0], loc[1])

        self.logger.info("Successfully imported application files")

    def importCMSIS(self):
        """Import CMSIS package and CMSIS-DEVICE adapter by ST inside the Eclipse project"""
        srcIncludeDir = os.path.join(self.cubemxprojectpath, "Drivers/CMSIS/Device/ST/STM32%sxx/Include" % self.HAL_TYPE)
        dstIncludeDir = os.path.join(self.eclipseprojectpath, "system/include/cmsis/device")
        srcCMSISIncludeDir = os.path.join(self.cubemxprojectpath, "Drivers/CMSIS/Include")
        dstCMSISIncludeDir = os.path.join(self.eclipseprojectpath, "system/include/cmsis")
        dstSourceDir = os.path.join(self.eclipseprojectpath, "system/src/cmsis")

        try:
            if not self.dryrun:
                os.mkdir(dstIncludeDir)
        except OSError:
            pass

        #Add includes to the project settings
        self.addCIncludes(("../system/include/cmsis/device",))
        self.addCPPIncludes(("../system/include/cmsis/device",))
        self.addAssemblerIncludes(("../system/include/cmsis/device",))

        # locations = ((srcIncludeDir, dstIncludeDir), (srcSourceDir, dstSourceDir))
        locations = ((srcIncludeDir, dstIncludeDir), (srcCMSISIncludeDir, dstCMSISIncludeDir))

        for loc in locations:
            self.copyTreeContent(loc[0], loc[1])

        systemFile = os.path.join(self.cubemxprojectpath, "Drivers/CMSIS/Device/ST/STM32%sxx/Source/Templates/system_stm32%sxx.c" % (self.HAL_TYPE, self.HAL_TYPE.lower()))
        startupFile = os.path.join(self.cubemxprojectpath, "Drivers/CMSIS/Device/ST/STM32%sxx/Source/Templates/gcc/startup_%s.s" % (self.HAL_TYPE, self.HAL_MCU_TYPE.lower()))
            
        locations = ((systemFile, dstSourceDir), (startupFile, dstSourceDir))

        if not self.dryrun:
            for loc in locations:
                shutil.copy(loc[0], loc[1])

            os.rename(os.path.join(self.eclipseprojectpath, "system/src/cmsis/startup_%s.s" % self.HAL_MCU_TYPE.lower()), os.path.join(self.eclipseprojectpath, "system/src/cmsis/startup_%s.S" % self.HAL_MCU_TYPE.lower()))
    
        self.logger.info("Successfully imported CMSIS files")

    def importHAL(self):
        """Import the ST HAL inside the Eclipse project"""
        srcIncludeDir = os.path.join(self.cubemxprojectpath, "Drivers/STM32%sxx_HAL_Driver/Inc" % self.HAL_TYPE)
        srcSourceDir = os.path.join(self.cubemxprojectpath, "Drivers/STM32%sxx_HAL_Driver/Src" % self.HAL_TYPE)
        dstIncludeDir = os.path.join(self.eclipseprojectpath, "system/include/stm32%sxx" % self.HAL_TYPE.lower())
        dstSourceDir = os.path.join(self.eclipseprojectpath, "system/src/stm32%sxx" % self.HAL_TYPE.lower())

        locations = ((srcIncludeDir, dstIncludeDir), (srcSourceDir, dstSourceDir))

        for loc in locations:
            self.copyTreeContent(loc[0], loc[1])

        self.addAssemblerMacros((self.HAL_MCU_TYPE,))
        self.addCMacros((self.HAL_MCU_TYPE,))
        self.addCPPMacros((self.HAL_MCU_TYPE,))

        if not self.dryrun:
            try:
                #Try to delete templete files, if generated
                os.unlink(os.path.join(self.eclipseprojectpath, "system/src/stm32%sxx/stm32%sxx_hal_msp_template.c" % (self.HAL_TYPE.lower(), self.HAL_TYPE.lower())))
                os.unlink(os.path.join(self.eclipseprojectpath, "system/src/stm32%sxx/stm32%sxx_hal_timebase_tim_template.c" % (self.HAL_TYPE.lower(), self.HAL_TYPE.lower())))
            except OSError:
                pass                

        self.logger.info("Successfully imported the STCubeHAL")

    def importMiddlewares(self):
        """Import the ST HAL inside the Eclipse project"""

        foundFreeRTOS = False
        foundMiddlewares = False
        foundFF = False
        foundLwIP = False

        for rootdir, dirs, files in os.walk(self.cubemxprojectpath):
            if "Middlewares" in dirs:
                foundMiddlewares = True
            if "FreeRTOS" in dirs:
                foundFreeRTOS = True
            if "FatFs" in dirs:
                foundFF = True
            if "LwIP" in dirs:
                foundLwIP = True

        if not foundMiddlewares:
            return

        srcDir = os.path.join(self.cubemxprojectpath, "Middlewares")
        dstDir = os.path.join(self.eclipseprojectpath, "Middlewares")

        locations = ((srcDir, dstDir),)

        try:
            for loc in locations:
                self.copyTree(loc[0], loc[1])
        except OSError as e:
            import errno
            if e.errno == errno.EEXIST:
                shutil.rmtree(dstDir)
                return self.importMiddlewares()

        #Adding Middleware library includes
        includes = [inc.replace("../../", "") for inc in self.getAC6Includes() if "Middlewares" in inc]

        self.addCIncludes(includes)
        self.addCPPIncludes(includes)
        self.addAssemblerIncludes(includes)
        self.addSourceEntries(("Middlewares",))
 
        self.logger.info("Successfully imported Middlewares libraries")

        if foundLwIP:
            try:
                ethernetif_template = os.path.join(self.eclipseprojectpath, "Middlewares/Third_Party/LwIP/src/netif/ethernetif_template.c")
                os.unlink(ethernetif_template)
            except OSError:  #CubeMX 4.14 no longer generates this file
                pass

        if foundFreeRTOS:
            print("#" * 100)
            print("####", end="")
            print("READ CAREFULLY".center(92), end="")
            print("####")
            print("#" * 100)
            print("""The original CubeMX project contains the FreeRTOS middleware library. 
This library was imported in the Eclipse project correctly, but you still need to
configure your tool-chain 'Float ABI' and 'FPU Type' if your STM32 support hard float 
(e.g. for a STM32F4 MCU set 'Float ABI'='FP Instructions(hard)'' and 'FPU Type'='fpv4-sp-d16'. 
Moreover, exclude from build those MemManage files (heap_1.c, etc) not needed for your project.""")

        if foundFF:
            print("#" * 100)
            print("####", end="")
            print("READ CAREFULLY".center(92), end="")
            print("####")
            print("#" * 100)
            print("""The original CubeMX project contains the FatFs middleware library. 
This library was imported in the Eclipse project correctly, but you still need to
exclude from build those uneeded codepage files (cc932.c, etc) not needed for your project.""")

        
    def parseEclipseProjectFile(self):
        """Parse the Eclipse XML project file"""
        projectFile = os.path.join(self.eclipseprojectpath, ".cproject")
        self.projectRoot = etree.fromstring(open(projectFile).read().encode('UTF-8'))
        
    def printEclipseProjectFile(self):
        """Do a pretty print of Eclipse project DOM"""
        xmlout = etree.tostring(self.projectRoot, pretty_print=True)
        #lxml correctly escapes the "&" to "&amp;", as specified by the XML standard.
        #However, Eclipse expects that the " charachter is espressed as &quot; So,
        #here we replace the "&amp;" with "&" in the final XML file
        xmlout = xmlout.replace("&amp;", "&")
        print(xmlout)

    def saveEclipseProjectFile(self):
        """Save the XML DOM of Eclipse project inside the .cproject file"""

        xmlout = '<?xml version="1.0" encoding="UTF-8" standalone="no"?><?fileVersion 4.0.0?>' + etree.tostring(self.projectRoot).decode('UTF-8')
        #lxml correctly escapes the "&" to "&amp;", as specified by the XML standard.
        #However, Eclipse expects that the " charachter is espressed as &quot; So,
        #here we replace the "&amp;" with "&" in the final XML file
        xmlout = xmlout.replace("&amp;", "&")
        projectFile = os.path.join(self.eclipseprojectpath, ".cproject")
        if not self.dryrun:
            open(projectFile, "w+").write(xmlout)

    def setDryRun(self, dryrun):
        """Enable dryrun mode: it does't execute operations on projects"""
        self.dryrun = dryrun
        if(dryrun > 0):
            self.logger.debug("Running in DryRun mode: the Eclipse project will not be modified")

class InvalidCubeMXFolder(Exception):
    pass
            
class InvalidEclipseFolder(Exception):
    pass

class InvalidSW4STM32Project(Exception):
    pass
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Import a CubeMX generated project inside an existing Eclipse project generated with the GNU ARM plugin')
    
    parser.add_argument('eclipse_path', metavar='eclipse_project_folder', type=str, 
                       help='an integer for the accumulator')

    parser.add_argument('cubemx_path', metavar='cubemx_project_folder', type=str, 
                       help='an integer for the accumulator')

    parser.add_argument('-v', '--verbose', type=int, action='store',
                       help='Verbose level')

    parser.add_argument('--dryrun', action='store_true', 
                       help="Doesn't perform operations - for debug purpose")

    args = parser.parse_args()

    if args.verbose == 3:
        logging.basicConfig(level=logging.DEBUG)
    if args.verbose == 2:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.ERROR )

    cubeImporter =  CubeMXImporter()
    cubeImporter.setDryRun(args.dryrun)
    cubeImporter.eclipseProjectPath = args.eclipse_path
    cubeImporter.cubeMXProjectPath = args.cubemx_path
    cubeImporter.parseEclipseProjectFile()
    cubeImporter.deleteOriginalEclipseProjectFiles()
    cubeImporter.importApplication()
    cubeImporter.importHAL()
    cubeImporter.importCMSIS()
    cubeImporter.importMiddlewares()
    cubeImporter.saveEclipseProjectFile()
    # cubeImporter.addCIncludes(["../middlewares/freertos"])
    # cubeImporter.printEclipseProjectFile()