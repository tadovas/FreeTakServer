#######################################################
# 
# orchestrator.py
# Python implementation of the Class orchestrator
# Generated by Enterprise Architect
# Created on:      21-May-2020 12:24:48 PM
# Original author: Natha Paquette
# 
#######################################################
import os
from FreeTAKServer.controllers.ReceiveConnections import ReceiveConnections
from FreeTAKServer.controllers.ClientInformationController import ClientInformationController
from FreeTAKServer.controllers.ClientSendHandler import ClientSendHandler
from FreeTAKServer.controllers.SendClientData import SendClientData
from FreeTAKServer.controllers.DataQueueController import DataQueueController
from FreeTAKServer.controllers.ClientInformationQueueController import ClientInformationQueueController
from FreeTAKServer.controllers.ActiveThreadsController import ActiveThreadsController
from FreeTAKServer.controllers.ReceiveConnectionsProcessController import ReceiveConnectionsProcessController
from FreeTAKServer.controllers.MainSocketController import MainSocketController
from FreeTAKServer.controllers.XMLCoTController import XMLCoTController
from FreeTAKServer.controllers.SendDataController import SendDataController
from FreeTAKServer.controllers.AsciiController import AsciiController
from FreeTAKServer.controllers.configuration.LoggingConstants import LoggingConstants
from FreeTAKServer.controllers.configuration.DataPackageServerConstants import DataPackageServerConstants as DPConst
from FreeTAKServer.model.RawCoT import RawCoT
from FreeTAKServer.controllers.SpecificCoTControllers.SendDisconnectController import SendDisconnectController
from FreeTAKServer.controllers.configuration.OrchestratorConstants import OrchestratorConstants
from FreeTAKServer.controllers.serializers.SqlAlchemyObjectController import SqlAlchemyObjectController
from FreeTAKServer.model.FTSModel.Event import Event
from FreeTAKServer.controllers.serializers.xml_serializer import XmlSerializer

ascii = AsciiController().ascii
from logging.handlers import RotatingFileHandler
import logging
import multiprocessing
import importlib
import sqlite3
import socket

loggingConstants = LoggingConstants()

from FreeTAKServer.controllers.ClientReceptionHandler import ClientReceptionHandler


class Orchestrator:
    #TODO: fix repeat attempts to add user
    # default constructor  def __init__(self):
    def __init__(self):
        log_format = logging.Formatter(loggingConstants.LOGFORMAT)
        self.logger = logging.getLogger(loggingConstants.LOGNAME)
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.newHandler(loggingConstants.DEBUGLOG, logging.DEBUG, log_format))
        self.logger.addHandler(self.newHandler(loggingConstants.ERRORLOG, logging.ERROR, log_format))
        self.logger.addHandler(self.newHandler(loggingConstants.INFOLOG, logging.INFO, log_format))
        # create necessary queues
        self.clientInformationQueue = []
        # this contains a list of all pipes which are transmitting CoT from clients
        self.pipeList = []
        # Internal Pipe used for CoT generated by the server itself
        self.internalCoTArray = []
        self.ClientReceptionHandlerEventPipe = ''
        # health check events
        self.healthCheckEventArray = []
        # instantiate controllers
        self.ActiveThreadsController = ActiveThreadsController()
        self.ClientInformationController = ClientInformationController()
        self.ClientInformationQueueController = ClientInformationQueueController()
        self.ClientSendHandler = ClientSendHandler()
        self.DataQueueController = DataQueueController()
        self.ReceiveConnections = ReceiveConnections()
        self.ReceiveConnectionsProcessController = ReceiveConnectionsProcessController()
        self.MainSocketController = MainSocketController()
        self.XMLCoTController = XMLCoTController()
        self.SendClientData = SendClientData()
        self.KillSwitch = 0
        self.openSockets = 0
        self.openSocketsArray = []

    def clear_user_table(self):
        self.dbController.remove_user()
        print('user table cleared')
    def testing(self):
        """
        function which creates variables for testing
        """
        from multiprocessing import Pipe
        from FreeTAKServer.controllers.DatabaseControllers.DatabaseController import DatabaseController
        self.dbController = DatabaseController()
        self.CoTSharePipe, other = Pipe()
        return None
    def newHandler(self, filename, log_level, log_format):
        handler = RotatingFileHandler(
            filename,
            maxBytes=loggingConstants.MAXFILESIZE,
            backupCount=loggingConstants.BACKUPCOUNT
        )
        handler.setFormatter(log_format)
        handler.setLevel(log_level)
        return handler

    def sendUserConnectionGeoChat(self, clientInformation):
        # TODO: refactor as it has a proper implementation of a PM to a user generated by the server
        '''
        function to create and send pm to connecting user
        :param clientInformation:
        :return:
        '''
        from FreeTAKServer.controllers.SpecificCoTControllers.SendGeoChatController import SendGeoChatController
        from FreeTAKServer.model.RawCoT import RawCoT
        from FreeTAKServer.model.FTSModel.Dest import Dest
        import uuid
        if OrchestratorConstants().DEFAULTCONNECTIONGEOCHATOBJ != None:
            ChatObj = RawCoT()
            ChatObj.xmlString = f'<event><point/><detail><remarks>{OrchestratorConstants().DEFAULTCONNECTIONGEOCHATOBJ}</remarks><marti><dest/></marti></detail></event>'

            classobj = SendGeoChatController(ChatObj, AddToDB=False)
            instobj = classobj.getObject()
            instobj.modelObject.detail._chat.chatgrp.setuid1(clientInformation.modelObject.uid)
            dest = Dest()
            dest.setcallsign(clientInformation.modelObject.detail.contact.callsign)
            instobj.modelObject.detail.marti.setdest(dest)
            instobj.modelObject.detail._chat.setchatroom(clientInformation.modelObject.detail.contact.callsign)
            instobj.modelObject.detail._chat.setparent("RootContactGroup")
            instobj.modelObject.detail._chat.setid(clientInformation.modelObject.uid)
            instobj.modelObject.detail._chat.setgroupOwner("True")
            instobj.modelObject.detail.remarks.setto(clientInformation.modelObject.uid)
            instobj.modelObject.setuid('GeoChat.'+'SERVER-UID.'+clientInformation.modelObject.detail.contact.callsign+'.'+str(uuid.uuid1()))
            instobj.modelObject.detail._chat.chatgrp.setid(clientInformation.modelObject.uid)
            classobj.reloadXmlString()
            SendDataController().sendDataInQueue(None, instobj, self.clientInformationQueue)
            return 1
        else:
            return 1
    def clientConnected(self, rawConnectionInformation):
        try:
            import copy
            # temporarily broken
            # self.check_for_dead_sockets()
            from FreeTAKServer.controllers.DatabaseControllers.EventTableController import EventTableController
            clientPipe = None
            self.logger.info(loggingConstants.CLIENTCONNECTED)
            clientInformation = self.ClientInformationController.intstantiateClientInformationModelFromConnection(
                rawConnectionInformation, clientPipe)
            sock = clientInformation.socket
            clientInformation.socket = None
            clint_info_clean = copy.deepcopy(clientInformation)
            clientInformation.socket = sock
            if self.checkOutput(clientInformation):
                pass
            else:
                raise Exception('error in the creation of client information')
            self.openSockets += 1
            #breaks ssl
            #self.ClientInformationQueueController.addClientToQueue(clientInformation)
            self.clientInformationQueue.append(clientInformation)
            try:
                if hasattr(clientInformation.socket, 'getpeercert'):
                    cn = "placeholder"
                else:
                    cn = None
                CoTRow = EventTableController().convert_model_to_row(clientInformation.modelObject)
                self.dbController.create_user(uid = clientInformation.modelObject.uid, callsign = clientInformation.modelObject.detail.contact.callsign, IP=clientInformation.IP, CoT = CoTRow, CN = cn)
            except Exception as e:
                print(e)
                self.logger.error(
                    'there has been an error in a clients connection while adding information to the database ' +
                    str(e))
            #self.logger.info(loggingConstants.CLIENTCONNECTEDFINISHED + str(clientInformation.modelObject.detail.contact.callsign))
            print("adding client")
            self.clientDataPipe.put(['add', clint_info_clean, self.openSockets])
            print("client added")
            self.sendUserConnectionGeoChat(clientInformation)
            return clientInformation
        except Exception as e:
            self.logger.warning(loggingConstants.CLIENTCONNECTEDERROR + str(e))
            return -1

    def check_for_dead_sockets(self):
        # fix function
        try:
            for sock in self.clientInformationQueue:
                if sock.is_alive():
                    pass
                else:
                    self.clientDisconnected(sock)
            return 1
        except Exception as e:
            self.logger.error("there has been an exception in checking for dead sockets " + str(e))
            return -1

    def emergencyReceived(self, processedCoT):
        try:
            if processedCoT.status == loggingConstants.ON:
                self.internalCoTArray.append(processedCoT)
                self.logger.debug(loggingConstants.EMERGENCYCREATED)
            elif processedCoT.status == loggingConstants.OFF:
                for CoT in self.internalCoTArray:
                    if CoT.type == "Emergency" and CoT.modelObject.uid == processedCoT.modelObject.uid:
                        self.internalCoTArray.remove(CoT)
                        self.logger.debug(loggingConstants.EMERGENCYREMOVED)
        except Exception as e:
            self.logger.error(loggingConstants.EMERGENCYRECEIVEDERROR + str(e))

    def dataReceived(self, RawCoT):
        # this will be executed in the event that the use case for the CoT isnt specified in the orchestrator
        try:
            # this will check if the CoT is applicable to any specific controllers
            RawCoT = self.XMLCoTController.determineCoTType(RawCoT)
            # the following calls whatever controller was specified by the above function
            module = importlib.import_module('FreeTAKServer.controllers.SpecificCoTControllers.' + RawCoT.CoTType)
            CoTSerializer = getattr(module, RawCoT.CoTType)
            #TODO: improve way in which the dbController is passed to CoTSerializer
            RawCoT.dbController = self.dbController
            processedCoT = CoTSerializer(RawCoT).getObject()
            sender = processedCoT.clientInformation
            # this will send the processed object to a function which will send it to connected clients
            '''try:
                # TODO: method of determining if CoT should be added to the internal array should
                #  be improved
                if processedCoT.type == "Emergency":
                    self.emergencyReceived(processedCoT)
                else:
                    pass
            except Exception as e:
                return -1'''
            return processedCoT
        except Exception as e:
            self.logger.error(loggingConstants.DATARECEIVEDERROR + str(e))
            return -1

    def sendInternalCoT(self, client):
        try:
            if len(self.internalCoTArray) > 0:
                for processedCoT in self.internalCoTArray:
                    SendDataController().sendDataInQueue(processedCoT.clientInformation, processedCoT, [client])
            else:
                pass
            self.send_active_emergencys(client)
            return 1
        except Exception as e:
            self.logger.error(loggingConstants.MONITORRAWCOTERRORINTERNALSCANERROR + str(e))
            return -1

    def send_active_emergencys(self, client):
        """
        this function needs to be cleaned up however it's functionality is as follows
        it query's the DB for active emergency's at which point it iterates over all
        emergency objects, transforms them into model objects and then xmlStrings
        finally the object is sent to the client.
        """
        try:

            from FreeTAKServer.model.SpecificCoT.SendEmergency import SendEmergency
            from lxml import etree
            emergencys = self.dbController.query_ActiveEmergency()
            for emergency in emergencys:
                emergencyobj = SendEmergency()
                modelObject = Event.emergecyOn()

                filledModelObject = SqlAlchemyObjectController().convert_sqlalchemy_to_modelobject(emergency.event, modelObject)
                # emergencyobj.setXmlString(XMLCoTController().serialize_model_to_CoT(filledModelObject))
                emergencyobj.setXmlString(etree.tostring((XmlSerializer().from_fts_object_to_format(filledModelObject))))
                print(emergencyobj.xmlString)
                emergencyobj.setModelObject(filledModelObject)
                SendDataController().sendDataInQueue(None, emergencyobj, [client])

        except Exception as e:
            import traceback
            self.logger.error(traceback.format_exc())
            self.logger.error('an exception has been thrown in sending active emergencies ' + str(e))

    def clientDisconnected(self, clientInformation):
        import time
        import traceback
        from copy import deepcopy
        self.logger.debug('client disconnected ' + "\n".join(traceback.format_stack()))
        print('disconnecting client')
        if hasattr(clientInformation, "clientInformation"):
            clientInformation = clientInformation.clientInformation
        """try:
            clientInformation.socket.send(b'sample')
            return 1
        except:
            try:
                clientInformation.socket.settimeout(0)
                if clientInformation.socket.recv() == b'':
                    pass
                else:
                    return 1
            except:
                return 1"""
        try:
            for client in self.clientInformationQueue:
                if client.ID == clientInformation.ID:
                    self.clientInformationQueue.remove(client)
                else:
                    pass
        except AttributeError:
            for client in self.clientInformationQueue:
                if client.ID == clientInformation.clientInformation.ID:
                    self.clientInformationQueue.remove(client)
                else:
                    pass
        except Exception as e:
            self.logger.critical("client removal failed "+str(e))
        try:
            self.ActiveThreadsController.removeClientThread(clientInformation)
            self.dbController.remove_user(query=f'uid = "{clientInformation.modelObject.uid}"')
        except Exception as e:
            self.logger.critical(
                'there has been an error in a clients disconnection while adding information to the database '+str(e))
            pass
        if hasattr(clientInformation, 'clientInformation'):
            clientInformation = clientInformation.clientInformation
        else:
            pass
        try:
            self.openSockets -= 1
            socketa = clientInformation.socket
            clientInformation.socket = None
            while clientInformation.socket != None: # this while loop prevents the put command ln 327 from failing as it ensures that the socket object is not present
                time.sleep(0.001)
            clientInformationcopy = deepcopy(clientInformation)
            print('stage 1 b')
            #time.sleep(1)

            self.clientDataPipe.put(['remove', clientInformationcopy, self.openSockets])
            #working
            #time.sleep(1)
            print('stage 1 c')
            clientInformation.socket = socketa
            try:
                clientInformation.socket.shutdown(socket.SHUT_RDWR)
            except Exception as e:
                self.logger.error('error shutting socket down in client disconnection')
                pass
            try:
                clientInformation.socket.close()
            except Exception as e:
                self.logger.error('error closing socket in client disconnection')
                pass

            self.logger.info(loggingConstants.CLIENTDISCONNECTSTART)
            # TODO: remove string
            tempXml = RawCoT()
            tempXml.xmlString = '<event><detail><link uid="{0}"/></detail></event>'.format(clientInformation.modelObject.uid).encode()
            disconnect = SendDisconnectController(tempXml)
            SendDataController().sendDataInQueue(disconnect.getObject().clientInformation, disconnect.getObject(), self.clientInformationQueue, self.CoTSharePipe)
            self.logger.info(loggingConstants.CLIENTDISCONNECTEND + str(clientInformation.modelObject.detail.contact.callsign))
            return 1
        except Exception as e:
            self.logger.error(loggingConstants.CLIENTCONNECTEDERROR + " " + str(e))
            pass

    def monitorRawCoT(self,data):
        # this needs to be the most robust function as it is the keystone of the program
        # this will attempt to define the type of CoT along with the designated controller
        try:
            if isinstance(data, int):
                return None
            else:
                CoT = XMLCoTController(logger=self.logger).determineCoTGeneral(data)
                function = getattr(self, CoT[0])
                output = function(CoT[1])
                return output
        except Exception as e:
            self.logger.error(loggingConstants.MONITORRAWCOTERRORB + str(e))
            return -1

    def checkOutput(self, output):
        if output != -1 and output != None:
            return True
        else:
            return False

    def loadAscii(self):
        ascii()

    def mainRunFunction(self, clientData, receiveConnection, sock, pool, event, clientDataPipe, ReceiveConnectionKillSwitch, CoTSharePipe, ssl = False):
        print('server started')
        if ssl:
            print("\n\n running ssl \n\n")
        self.ssl = ssl
        import datetime
        receiveconntimeoutcount = datetime.datetime.now()
        lastprint = datetime.datetime.now()
        while event.is_set():
            self.CoTSharePipe = CoTSharePipe
            try:
                if ssl == True:
                    pass
                self.clientDataPipe = clientDataPipe
                if event.is_set():
                    try:
                        if ReceiveConnectionKillSwitch.is_set():
                            try:
                                receiveConnection.successful()
                            except:
                                pass
                            ReceiveConnectionKillSwitch.clear()
                            receiveConnection = pool.apply_async(ReceiveConnections().listen,
                                                                 (sock,))
                        else:
                            receiveConnectionOutput = receiveConnection.get(timeout=0.01)
                            receiveConnection = pool.apply_async(ReceiveConnections().listen, (sock, ssl,))
                            receiveconntimeoutcount = datetime.datetime.now()
                            lastprint = datetime.datetime.now()
                            CoTOutput = self.handel_connection_data(receiveConnectionOutput)

                    except multiprocessing.TimeoutError:

                        if (datetime.datetime.now() - receiveconntimeoutcount) > datetime.timedelta(seconds=60) and ssl == True:
                            from multiprocessing.pool import ThreadPool
                            try:
                                pass
                                print('\n\nresetting\n\n')
                                pool.terminate()
                                pool = ThreadPool(processes=2)
                                self.pool = pool
                                receiveconntimeoutcount = datetime.datetime.now()
                                lastprint = datetime.datetime.now()
                                clientData = pool.apply_async(ClientReceptionHandler().startup,
                                                              (self.clientInformationQueue,))
                                receiveConnection = pool.apply_async(ReceiveConnections().listen, (sock, ssl,))
                            except Exception as e:
                                print(str(e))
                        elif ssl == True and (datetime.datetime.now() - lastprint) > datetime.timedelta(seconds=30):
                            print('time since last reset ' + str(datetime.datetime.now() - receiveconntimeoutcount))
                            lastprint = datetime.datetime.now()
                        else:
                            pass
                    except Exception as e:
                        self.logger.error('exception in receive connection within main run function '+str(e))

                    try:
                        clientDataOutput = clientData.get(timeout=0.01)
                        if self.checkOutput(clientDataOutput) and isinstance(clientDataOutput, list):
                            CoTOutput = self.handel_regular_data(clientDataOutput)
                        else:
                            raise Exception('client reception handler has returned data which is not of type list data is ' + str(clientDataOutput))
                        clientData = pool.apply_async(ClientReceptionHandler().startup, (self.clientInformationQueue,))
                    except multiprocessing.TimeoutError:
                        pass
                    except Exception as e:
                        #self.logger.info('exception in receive client data within main run function ' + str(e))
                        pass
                    try:
                        if not CoTSharePipe.empty():
                            # print('getting share pipe data')

                            data = CoTSharePipe.get()
                            CoTOutput = self.handel_shared_data(data)
                        else:
                            pass
                    except Exception as e:
                        self.logger.error('there has been an excepion in the handling of data supplied by the rest API '+str(e))
                        pass
                else:
                    self.stop()
                    break
            except Exception as e:
                self.logger.info('there has been an uncaught error thrown in mainRunFunction' + str(e))
                pass
        self.stop()

    def handel_shared_data(self, modelData):
        try:
            #print('\n \n handling shared data \n \n')
            # print('data received within orchestrator '+str(modelData.xmlString))
            if hasattr(modelData, 'clientInformation'):
                output = SendDataController().sendDataInQueue(modelData.clientInformation, modelData,
                                                              self.clientInformationQueue)
            #

            elif modelData.type == "connmessage":
                self.internalCoTArray.append(modelData)

            # this runs in the event of a new connection
            else:
                print(modelData)
                output = SendDataController().sendDataInQueue(None, modelData,
                                                              self.clientInformationQueue)
        except Exception as e:
            self.logger.error("data base connection error " + str(e))
            print(e)

    def handel_regular_data(self, clientDataOutput):
        try:
            for clientDataOutputSingle in clientDataOutput:
                try:
                    print('handling reg data')
                    if clientDataOutputSingle == -1:
                        continue
                    CoTOutput = self.monitorRawCoT(clientDataOutputSingle)
                    if CoTOutput == 1:
                        continue
                    elif self.checkOutput(CoTOutput):
                        output = SendDataController().sendDataInQueue(CoTOutput.clientInformation, CoTOutput,
                                                                      self.clientInformationQueue, self.CoTSharePipe)
                        if self.checkOutput(output) and isinstance(output, tuple) == False:
                            pass
                        elif isinstance(output, tuple):
                            self.logger.error('issue sending data to client now disconnecting')
                            self.clientDisconnected(output[1])

                        else:
                            self.logger.error('send data failed in main run function with data ' + str(
                                CoTOutput.xmlString) + ' from client ' + CoTOutput.clientInformation.modelObject.detail.contact.callsign)

                    else:
                        raise Exception('error in general data processing')
                except Exception as e:
                    self.logger.info(
                        'exception in client data, data processing within main run function ' + str(
                            e) + ' data is ' + str(CoTOutput))
                    pass
                except Exception as e:
                    self.logger.info(
                        'exception in client data, data processing within main run function ' + str(
                            e) + ' data is ' + str(clientDataOutput))
        except Exception as e:
            self.logger.info("there has been an error iterating client data output " + str(e))
            return -1
        return 1

    def handel_connection_data(self, receiveConnectionOutput):
        try:
            print('handling conn data')
            if receiveConnectionOutput == -1:
                return None

            CoTOutput = self.monitorRawCoT(receiveConnectionOutput)
            if CoTOutput != -1 and CoTOutput != None:
                output = SendDataController().sendDataInQueue(CoTOutput, CoTOutput,
                                                              self.clientInformationQueue, self.CoTSharePipe)
                if self.checkOutput(output):
                    self.logger.debug('connection data from client ' + str(CoTOutput.modelObject.detail.contact.callsign) + ' successfully processed')
                else:
                    raise Exception('error in sending data')
            else:
                pass
        except Exception as e:
            self.logger.error('exception in receive connection data processing within main run function ' + str(
                e) + ' data is ' + str(CoTOutput))
            return -1
        self.sendInternalCoT(CoTOutput)
        return 1

    def start(self, IP, CoTPort, Event, clientDataPipe, ReceiveConnectionKillSwitch, RestAPIPipe):
        try:
            self.db = sqlite3.connect(DPConst().DATABASE)
            os.chdir('../../../')
            # create socket controller
            self.MainSocketController.changeIP(IP)
            self.MainSocketController.changePort(CoTPort)
            sock = self.MainSocketController.createSocket()
            #changed
            from multiprocessing.pool import ThreadPool
            pool = ThreadPool(processes=2)
            self.pool = pool
            clientData = pool.apply_async(ClientReceptionHandler().startup, (self.clientInformationQueue,))
            receiveConnection = pool.apply_async(ReceiveConnections().listen, (sock,))
            # instantiate domain model and save process as object
            self.mainRunFunction(clientData, receiveConnection, sock, pool, Event, clientDataPipe, ReceiveConnectionKillSwitch, RestAPIPipe)

        except Exception as e:
            self.logger.critical('there has been a critical error in the startup of FTS' + str(e))
            return -1

    def stop(self):
        self.clientDataPipe.close()
        self.pool.terminate()
        self.pool.close()
        self.pool.join()

"""if __name__ == "__main__":

    parser = argparse.ArgumentParser(description=OrchestratorConstants().FULLDESC)
    parser.add_argument(OrchestratorConstants().COTPORTARG, type=int, help=OrchestratorConstants().COTPORTDESC,
                        default=OrchestratorConstants().COTPORT)
    parser.add_argument(OrchestratorConstants().IPARG, type=str, help=OrchestratorConstants().IPDESC,
                        default=OrchestratorConstants().IP)
    parser.add_argument(OrchestratorConstants().APIPORTARG, type=int, help=OrchestratorConstants().APIPORTDESC,
                        default=DataPackageServerConstants().APIPORT)
    args = parser.parse_args()
    CreateStartupFilesController()
    Orchestrator().start(args.IP, args.CoTPort, args.APIPort)"""