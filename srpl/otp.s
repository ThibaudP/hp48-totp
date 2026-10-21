* otp.s -- the app's main program (OTP), in System RPL.
*
*   Home view (mode 0): every account and its current code; up/down select,
*     ENTER or right opens; ADD REN DEL MOVE TIME QUIT.
*   Account view (mode 1): previous / current (big) / next code; BACK (or left),
*     PREV/NEXT (or up/down) switch account, TZ toggles CET/CEST, QUIT.
*   Move (mode 2): up/down move the selected account; ENTER or MOVE ends.
*
* Why System RPL: no argument checks on every command, system binary integers
* instead of 10.5-byte reals for counters and coordinates, drawing straight into
* the display (HARDBUFF).  A 48G has ~12 KB free with the app installed, and
* every byte allocated brings the next garbage collection (seconds long) closer.
*
* Timing: the countdown only needs the seconds within the minute (unix mod 30
* equals local seconds mod 30, time zones being whole hours), read with TIME by
* the SECS helper.  The full Unix time (UNIX) is read once per 30 s window, to
* compute codes; the next window's codes are computed ahead, one per second.
*
* Rarely used parts stay in User RPL and are called by name: INIT, UNIX, SECS,
* W25 (.25 WAIT), OFFH (OFF), LBLS, TZL, DIGS, SWAP2, ADDA, RENA, DELA, TIMEA.
*
* System RPL key codes: soft keys A-F = 1-6, up 11, left 16, down 17, right 18,
* ENTER 25.
*
* Local variables (NULLLAM; 1GETLAM is the last value bound):
*  1 done?   2 mode   3 selected account   4 first visible row
*  5 home labels   6 account labels
*  7 home codes (list of $)   8 their window (%)
*  9 account codes { prev cur next }   10 their account   11 their window (%)
* 12 last second drawn, 0-29 within the window (%; -1: redraw in full)
* 13 redraw?   14 next window's home codes, being built   15 next index
* 16 account code two windows ahead ("" if none)   17 its account
* 18 current window (%)   19 window of the last key (%; -1: none yet)
* 20 home bar (131x2 black)   21 account bar (90x4 black)   22 home row drawer

ASSEMBLE
        NIBASC  \HPHP48-E\
RPL

DEFINE DONE@    1GETLAM
DEFINE DONE!    1PUTLAM
DEFINE MODE@    2GETLAM
DEFINE MODE!    2PUTLAM
DEFINE SEL@     3GETLAM
DEFINE SEL!     3PUTLAM
DEFINE TOP@     4GETLAM
DEFINE TOP!     4PUTLAM
DEFINE HLBL@    5GETLAM
DEFINE DLBL@    6GETLAM
DEFINE HC@      7GETLAM
DEFINE HC!      7PUTLAM
DEFINE HW@      8GETLAM
DEFINE HW!      8PUTLAM
DEFINE DC@      9GETLAM
DEFINE DC!      9PUTLAM
DEFINE DA@      10GETLAM
DEFINE DA!      10PUTLAM
DEFINE DW@      11GETLAM
DEFINE DW!      11PUTLAM
DEFINE LS@      12GETLAM
DEFINE LS!      12PUTLAM
DEFINE RD@      13GETLAM
DEFINE RD!      13PUTLAM
DEFINE NX@      14GETLAM
DEFINE NX!      14PUTLAM
DEFINE NI@      15GETLAM
DEFINE NI!      15PUTLAM
DEFINE D2@      16GETLAM
DEFINE D2!      16PUTLAM
DEFINE DR@      17GETLAM
DEFINE DR!      17PUTLAM
DEFINE CW@      18GETLAM
DEFINE CW!      18PUTLAM
DEFINE LK@      19GETLAM
DEFINE LK!      19PUTLAM
DEFINE HBAR@    20GETLAM
DEFINE DBAR@    21GETLAM
DEFINE HROW     22GETLAM EVAL

DEFINE NACCTS   ID ACCTS LENCOMP

* #k %c -> "123456": the code of account k for window c (calls HOTP)
DEFINE CODEF    :: ID ACCTS ROT NTHCOMPDROP TWO NTHCOMPDROP SWAP %># ID WRK ID HOTP HXS>% % 1000000 %MOD COERCE #>$ "000000" SWAP &$ DUPLEN$ DUP #5- SWAP SUB$ ;

* "123456" -> "123 456"
DEFINE FMT7     :: DUP ONE THREE SUB$ " " &$ SWAP FOUR SIX SUB$ &$ ;

* grob #x #y -> (draws grob on the screen at x, y)
DEFINE SHOW     :: HARDBUFF UNROT GROB! ;

* $ #y -> (draws $ centered on row y, medium font)
DEFINE CENTER   :: SWAP $>GROB DUPGROBDIM SWAPDROP # 83 SWAP #- #2/ ROT SHOW ;

* $ #y -> (draws $ right-aligned on row y)
DEFINE RIGHT    :: SWAP $>GROB DUPGROBDIM SWAPDROP # 83 SWAP #- ROT SHOW ;

* #left -> "18s" / " 9s"
DEFINE SECS$    :: DUP #>$ SWAP TEN #< IT :: " " SWAP &$ ; "s" &$ ;

* #x1 #y1 #x2 #y2 -> (clears that rectangle of the screen)
DEFINE CLEAR    :: HARDBUFF 5UNROLL GROB!ZERO DROP ;

* $prev $cur $next -> (draws the account view's three codes)
DEFINE DCODES   :: "next  " SWAP FMT7 &$ # 28 CENTER SEVEN ONE DO DUP INDEX@ INDEX@ SUB$ CAR$ CHR># # 2F #- ID DIGS SWAP NTHCOMPDROP INDEX@ #1- # 11 #* # B #+ INDEX@ THREE #> IT :: SIX #+ ; # 12 SHOW LOOP DROP "prev  " SWAP FMT7 &$ NINE CENTER ;

* #k -> (draws home row k: name, code, inverted if selected)
DEFINE ROWDEF   :: EIGHT # 83 MAKEGROB ID ACCTS 3PICK NTHCOMPDROP ONE NTHCOMPDROP $>GROB OVER TWO ZERO GROB! HC@ 3PICK NTHCOMPDROP FMT7 $>GROB OVER # 57 ZERO GROB! OVER SEL@ #= IT INVGROB SWAP TOP@ #- EIGHT #* TWELVE #+ ZERO SWAP SHOW ;

::
  CK0NOLASTWD
  ID INIT
  ' ROWDEF                                  ( 22 home row drawer )
  FOUR # 5A MAKEGROB INVGROB                ( 21 account bar )
  TWO # 83 MAKEGROB INVGROB                 ( 20 home bar )
  % -1 % -1 ZERO NULL$ ONE NULL{} TRUE      ( 19 .. 13 )
  % -1 % -1 ZERO NULL{} % -1 NULL{}         ( 12 .. 7 )
  { "BACK" "PREV" "NEXT" "TZ" "" "QUIT" } ID LBLS     ( 6 )
  { "ADD" "REN" "DEL" "MOVE" "TIME" "QUIT" } ID LBLS  ( 5 )
  ONE ONE ZERO FALSE                        ( 4 .. 1 )
  { NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM
    NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM NULLLAM }
  BIND
  BEGIN
    ID SECS DUP %IP % 30 %MOD               ( %S %s30 )

    ( new window, redraw requested, or first pass: read the clock, get codes, draw )
    DUP LS@ %< RD@ OR LS@ % -1 %= OR IT
    ::
      ID UNIX % 30 %/ %IP CW!
      LK@ % -1 %= IT :: CW@ LK! ;
      NACCTS SEL@ #< IT :: NACCTS ONE #MAX SEL! TRUE RD! ;
      NACCTS #0= MODE@ ONE #= AND IT :: ZERO MODE! TRUE RD! ;
      MODE@ ONE #=
      ITE
      ::                                      ( account view: codes )
        DW@ CW@ %= DA@ SEL@ #= AND NOT IT
        ::
          CW@ DW@ %1+ %= DA@ SEL@ #= AND DR@ SEL@ #= AND D2@ LEN$ #0<> AND
          ITE
          :: DC@ TWO NTHCOMPDROP DC@ THREE NTHCOMPDROP D2@ ;
          ::
            SEL@ CW@ %1- CODEF
            HW@ CW@ %= ITE :: HC@ SEL@ NTHCOMPDROP ; :: SEL@ CW@ CODEF ;
            SEL@ CW@ %1+ CODEF
          ;
          THREE {}N DC!
          NULL$ D2!
          DA@ SEL@ #= RD@ NOT AND
          ITE :: DC@ INCOMPDROP DCODES ; :: TRUE RD! ;
          CW@ DW! SEL@ DA!
        ;
      ;
      ::                                      ( home view: codes )
        HW@ CW@ %= NOT IT
        ::
          CW@ HW@ %1+ %= NI@ NACCTS #> AND
          ITE
          :: NX@ ;
          :: NACCTS #0= ITE NULL{}
             :: NACCTS #1+ ONE DO INDEX@ CW@ CODEF LOOP NACCTS {}N ; ;
          HC!
          NULL{} NX! ONE NI!
          HW@ % -1 %= RD@ OR
          ITE :: TRUE RD! ; :: TOP@ FOUR #+ NACCTS #MIN #1+ TOP@ DO INDEX@ HROW LOOP ;
          CW@ HW!
        ;
      ;
      RD@ IT
      ::
        RECLAIMDISP TURNMENUOFF
        MODE@ ONE #=
        ITE
        ::                                    ( account view, in full )
          ID ACCTS SEL@ NTHCOMPDROP ONE NTHCOMPDROP $>GROB ZERO ZERO SHOW
          SEL@ #>$ "/" &$ NACCTS #>$ &$ " " &$ ID TZL &$ ZERO RIGHT
          DC@ INCOMPDROP DCODES
          DLBL@ ZERO # 38 SHOW
        ;
        ::                                    ( home view, in full )
          "TOTP" $>GROB ZERO ZERO SHOW
          MODE@ TWO #= ITE :: "MOVE" ; :: ID TZL ; ZERO RIGHT
          NACCTS #0=
          ITE
          :: "No accounts yet:" # 14 CENTER "press ADD" # 1E CENTER ;
          :: TOP@ FOUR #+ NACCTS #MIN #1+ TOP@ DO INDEX@ HROW LOOP ;
          HLBL@ ZERO # 38 SHOW
        ;
        FALSE RD!
      ;
      % -1 LS!                                ( redraw the countdown in full below )
    ;

    ( countdown, when the second changed )
    DUP LS@ %= NOT IT
    ::
      % 30 OVER %- COERCE                     ( %S %s30 #left )
      MODE@ ONE #=
      ITE
      ::
        LS@ % -1 %= IT :: DBAR@ TWO # 32 SHOW ;
        DUP THREE #* TWO #+ # 32 # 5C # 36 CLEAR
        SECS$ $>GROB # 71 # 30 SHOW
      ;
      ::
        LS@ % -1 %= IT :: HBAR@ ZERO NINE SHOW ;
        DUP UNCOERCE % 131 %* % 30 %/ %IP COERCE NINE # 83 # B CLEAR
        SECS$ $>GROB # 50 ZERO SHOW
      ;
      DUP LS!
      ( one code of the next window, computed ahead )
      MODE@ ONE #=
      ITE
      :: D2@ LEN$ #0= IT :: SEL@ CW@ %1+ %1+ CODEF D2! SEL@ DR! ; ;
      :: NI@ NACCTS #> NOT IT
         :: NX@ NI@ CW@ %1+ CODEF ONE {}N &COMP NX! NI@ #1+ NI! ; ;
    ;
    DROP                                      ( %S )

    ( wait for a key or the next second, in quarter seconds )
    %FP %1 SWAP %- % 4 %* %CEIL COERCE ONE #MAX
    ZERO SWAP ZERO DO
      DUP #0= IT :: GETTOUCH ITE SWAPDROP :: ID W25 ; ;
    LOOP                                      ( #key or 0 )

    DUP #0<> IT :: CW@ LK! ;
    CW@ LK@ %- % 6 %> IT :: ID OFFH CW@ LK! TRUE RD! ;

    MODE@ ONE #=
    ITE
    ::                                        ( account view )
      DUP ONE #= OVER SIXTEEN #= OR IT :: ZERO MODE! TRUE RD! ;
      DUP TWO #= OVER ELEVEN #= OR IT :: SEL@ ONE #= ITE :: NACCTS ; :: SEL@ #1- ; SEL! % -1 LS! ;
      DUP THREE #= OVER SEVENTEEN #= OR IT :: SEL@ NACCTS #= ITE ONE :: SEL@ #1+ ; SEL! % -1 LS! ;
      DUP FOUR #= IT :: % 3 ID TZ %- ' ID TZ STO TRUE RD! % -1 DW! ;
      DUP SIX #= IT :: TRUE DONE! ;
    ;
    ::
      MODE@ TWO #=
      ITE
      ::                                      ( move )
        DUP ELEVEN #= SEL@ ONE #> AND IT
        :: ID ACCTS SEL@ UNCOERCE SEL@ #1- UNCOERCE ID SWAP2 ' ID ACCTS STO
           HC@ SEL@ UNCOERCE SEL@ #1- UNCOERCE ID SWAP2 HC!
           SEL@ #1- SEL! TRUE RD! ;
        DUP SEVENTEEN #= SEL@ NACCTS #< AND IT
        :: ID ACCTS SEL@ UNCOERCE SEL@ #1+ UNCOERCE ID SWAP2 ' ID ACCTS STO
           HC@ SEL@ UNCOERCE SEL@ #1+ UNCOERCE ID SWAP2 HC!
           SEL@ #1+ SEL! TRUE RD! ;
        DUP TWENTYFIVE #= OVER FOUR #= OR IT :: ZERO MODE! TRUE RD! ;
      ;
      ::                                      ( home )
        DUP ELEVEN #= OVER SEVENTEEN #= OR NACCTS #0<> AND IT
        ::
          DUP ELEVEN #= ITE :: SEL@ #1- ; :: SEL@ #1+ ; ONE #MAX NACCTS #MIN   ( #v )
          DUP TOP@ #<
          ITE
          :: DUP FIVE #> ITE :: DUP FOUR #- ; ONE TOP! SEL! TRUE RD! ;
          ::
            DUP TOP@ FOUR #+ #>
            ITE
            :: DUP TOP! SEL! TRUE RD! ;
            :: SEL@ SWAP SEL! HROW SEL@ HROW ;
          ;
        ;
        DUP TWENTYFIVE #= OVER EIGHTEEN #= OR NACCTS #0<> AND IT :: ONE MODE! ZERO DA! TRUE RD! ;
        DUP ONE #= IT
        :: ID ADDA %0<> IT :: NACCTS SEL! ONE MODE! ;
           % -1 HW! % -1 DW! TRUE RD! ;
        DUP TWO #= NACCTS #0<> AND IT :: SEL@ UNCOERCE ID RENA TRUE RD! ;
        DUP THREE #= NACCTS #0<> AND IT :: SEL@ UNCOERCE ID DELA DROP % -1 HW! % -1 DW! TRUE RD! ;
        DUP FOUR #= NACCTS ONE #> AND IT :: TWO MODE! TRUE RD! ;
        DUP FIVE #= IT :: ID TIMEA % -1 HW! TRUE RD! ;
        DUP SIX #= IT :: TRUE DONE! ;
        ( keep the selection on screen )
        SEL@ TOP@ #< IT :: SEL@ TOP! TRUE RD! ;
        SEL@ TOP@ FOUR #+ #> IT :: SEL@ FOUR #- TOP! TRUE RD! ;
      ;
    ;
    DROP
    DONE@
  UNTIL
  ABND
  RECLAIMDISP TURNMENUON ClrDAsOK
;
