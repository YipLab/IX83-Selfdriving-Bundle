//PINOUT of arduino
int pinEn[] = {2,7,13,8};
int pinPos[] = {3,5,11,9};
int pinNeg[] = {4,6,12,10};
int switchCount = 2;

//Constants
bool disEn = false; //disables enable after desired amount of time
int waitTime = 1000; //Wait time until disable in ms

void setup() {
  //init serial
  Serial.begin(9600);
  // init output pins
  for (int i=0; i<switchCount; i++){
    pinMode(pinEn[i], OUTPUT);
    pinMode(pinPos[i], OUTPUT);
    pinMode(pinNeg[i], OUTPUT);

    changeState(i, 0); //Closes shutters
  }
  //
  Serial.println("Yip Lab Shutters V2");
}

void loop() {
  if (Serial.available() > 2){
    int val = Serial.parseInt();
    //Serial.println(val);
    int sw = (val/10)%10;
    int st = val%10;
    //Serial.println(sw);
    //Serial.println(st);
    changeState(sw, st);    
  }
}

void changeState(int swi, int sta){
  digitalWrite(pinEn[swi], HIGH);
  digitalWrite(pinPos[swi], sta);
  digitalWrite(pinNeg[swi], sta-1);
  if (disEn){
    delay(waitTime);
    digitalWrite(pinEn[swi], LOW);
  }
}
