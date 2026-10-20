/*
 * satrun: run Saturn machine code on x48ng's CPU core with a flat 1M-nibble memory.
 * No ROM, no display, no interrupts: just the CPU, for unit-testing routines.
 *
 * Commands on stdin, one per line (numbers are hex):
 *   load FILE ADDR       load a binary (HPHP48- header skipped) at ADDR, nibbles low-first
 *   poke ADDR NIBBLES    write nibbles in memory order (lowest address first)
 *   reg NAME VALUE       set A B C D R0-R4 (64-bit, most significant digit first),
 *                        D0 D1 PC P ST(16 bits) CARRY, or MODE HEX|DEC
 *   break ADDR           print "brk ADDR" and registers each time PC reaches ADDR
 *   call ADDR [MAX]      push a sentinel return address, jump to ADDR and run until
 *                        it returns (RTN family) or MAX instructions (default 10000000)
 *   run ADDR STOP [MAX]  jump to ADDR and run until PC == STOP
 *   regs                 print registers
 *   dump ADDR N          print N nibbles starting at ADDR, lowest address first
 *   # ...                comment
 * After call/run: "done STEPS" or "timeout STEPS" or "illegal PC". Exit status 1 on error.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "core/debugger.h"
#include "core/emulate.h"
#include "core/memory.h"
#include "core/timers.h"
#include "options.h"

#define MEM_SIZE 0x100000
#define SENTINEL 0xFFFF0
#define MAX_BREAKS 64

static Nibble mem[ MEM_SIZE ];
static long breaks[ MAX_BREAKS ];
static int nbreaks;

/* Hooks and globals the CPU core expects from the rest of x48ng. */
static Nibble flat_fetch( Address a ) { return mem[ a & ( MEM_SIZE - 1 ) ]; }
static void flat_write( Address a, Nibble v ) { mem[ a & ( MEM_SIZE - 1 ) ] = v & 0xf; }
static int flat_crc( Address a ) { return mem[ a & ( MEM_SIZE - 1 ) ]; }
Nibble ( *bus_fetch_nibble )( Address ) = flat_fetch;
void ( *bus_write_nibble )( Address, Nibble ) = flat_write;
int ( *read_nibble_crc )( Address ) = flat_crc;
long nibble_masks[ 16 ] = { 0x0000000f, 0x000000f0, 0x00000f00, 0x0000f000, 0x000f0000, 0x00f00000, 0x0f000000, 0xf0000000,
                            0x0000000f, 0x000000f0, 0x00000f00, 0x0000f000, 0x000f0000, 0x00f00000, 0x0f000000, 0xf0000000 };
int enter_debugger = 0;
bool in_debugger = false;
config_t x48ng_config;
long read_nibbles( Address addr, int len )
{
    long val = 0;
    for ( addr += len; len > 0; len-- )
        val = ( val << 4 ) | flat_fetch( --addr );
    return val;
}
t1_t2_ticks get_t1_t2( void ) { return ( t1_t2_ticks ){ 0, 0 }; }
void reset_timer( int t ) { ( void )t; }
void restart_timer( int t ) { ( void )t; }
void start_timer( int t ) { ( void )t; }
void stop_timer( int t ) { ( void )t; }
void receive_char( void ) {}
void transmit_char( void ) {}
void serial_baud( int b ) { ( void )b; }
void ui4x_handle_pending_inputs( void ) {}
void ui4x_refresh_output( void ) {}

static void fail( const char* msg, const char* arg )
{
    fprintf( stderr, "satrun: %s%s%s\n", msg, arg ? ": " : "", arg ? arg : "" );
    exit( 1 );
}

static long hex( const char* s )
{
    char* end;
    if ( !s )
        fail( "missing argument", NULL );
    long v = strtol( s, &end, 16 );
    if ( *end )
        fail( "bad hex number", s );
    return v;
}

static void set_reg64( Nibble* r, const char* s )
{
    size_t n = strlen( s );
    if ( n == 0 || n > 16 )
        fail( "register value must be 1-16 hex digits", s );
    memset( r, 0, 16 );
    for ( size_t i = 0; i < n; i++ )
        r[ i ] = ( Nibble )hex( ( char[] ){ s[ n - 1 - i ], 0 } );
}

static void print_reg64( const char* name, const Nibble* r )
{
    printf( "%s=", name );
    for ( int i = 15; i >= 0; i-- )
        printf( "%X", r[ i ] );
    printf( " " );
}

static void print_regs( void )
{
    static const char* names[] = { "A", "B", "C", "D" };
    char rn[ 3 ] = "R0";
    for ( int i = 0; i < 4; i++ )
        print_reg64( names[ i ], saturn.reg[ i ] );
    for ( int i = 0; i < 5; i++ ) {
        rn[ 1 ] = ( char )( '0' + i );
        print_reg64( rn, saturn.reg_r[ i ] );
    }
    int st = 0;
    for ( int i = 3; i >= 0; i-- )
        st = ( st << 4 ) | saturn.st[ i ];
    printf( "D0=%05lX D1=%05lX P=%X PC=%05lX ST=%04X CARRY=%d MODE=%s RSTK=%d\n", saturn.d[ 0 ], saturn.d[ 1 ], saturn.p, saturn.pc, st,
            saturn.carry, saturn.hexmode == HEX ? "HEX" : "DEC", saturn.rstk_ptr + 1 );
}

static void load( const char* fname, Address addr )
{
    FILE* f = fopen( fname, "rb" );
    if ( !f )
        fail( "cannot open", fname );
    unsigned char hdr[ 8 ];
    size_t n = fread( hdr, 1, 7, f );
    if ( !( n == 7 && memcmp( hdr, "HPHP48-", 7 ) == 0 && fread( hdr, 1, 1, f ) == 1 ) )
        rewind( f );
    int c;
    while ( ( c = fgetc( f ) ) != EOF ) {
        flat_write( addr++, c & 0xf );
        flat_write( addr++, c >> 4 );
    }
    fclose( f );
}

static void execute( Address start, Address stop, long max )
{
    long steps = 0;
    saturn.pc = start;
    enter_debugger = 0;
    while ( saturn.pc != stop ) {
        if ( steps >= max ) {
            printf( "timeout %ld\n", steps );
            return;
        }
        for ( int i = 0; i < nbreaks; i++ )
            if ( saturn.pc == breaks[ i ] ) {
                printf( "brk %05lX ", saturn.pc );
                print_regs();
            }
        Address pc = saturn.pc;
        step_instruction();
        steps++;
        if ( enter_debugger & ILLEGAL_INSTRUCTION ) {
            printf( "illegal %05lX\n", pc );
            return;
        }
    }
    printf( "done %ld\n", steps );
}

int main( void )
{
    char line[ 4096 ];
    saturn.hexmode = HEX;
    saturn.rstk_ptr = -1;

    while ( fgets( line, sizeof line, stdin ) ) {
        char* argv[ 8 ] = { 0 };
        int argc = 0;
        for ( char* t = strtok( line, " \t\r\n" ); t && argc < 8; t = strtok( NULL, " \t\r\n" ) )
            argv[ argc++ ] = t;
        if ( argc == 0 || argv[ 0 ][ 0 ] == '#' )
            continue;
        const char* cmd = argv[ 0 ];

        if ( !strcmp( cmd, "load" ) ) {
            load( argv[ 1 ] ? argv[ 1 ] : "", hex( argv[ 2 ] ) );
        } else if ( !strcmp( cmd, "poke" ) ) {
            Address a = hex( argv[ 1 ] );
            for ( const char* p = argv[ 2 ] ? argv[ 2 ] : ""; *p; p++ )
                flat_write( a++, ( Nibble )hex( ( char[] ){ *p, 0 } ) );
        } else if ( !strcmp( cmd, "reg" ) ) {
            const char* n = argv[ 1 ] ? argv[ 1 ] : "";
            const char* v = argv[ 2 ];
            if ( !v )
                fail( "missing value for", n );
            if ( strlen( n ) == 1 && strchr( "ABCD", n[ 0 ] ) )
                set_reg64( saturn.reg[ n[ 0 ] - 'A' ], v );
            else if ( n[ 0 ] == 'R' && n[ 1 ] >= '0' && n[ 1 ] <= '4' && !n[ 2 ] )
                set_reg64( saturn.reg_r[ n[ 1 ] - '0' ], v );
            else if ( !strcmp( n, "D0" ) || !strcmp( n, "D1" ) )
                saturn.d[ n[ 1 ] - '0' ] = hex( v ) & 0xfffff;
            else if ( !strcmp( n, "PC" ) )
                saturn.pc = hex( v ) & 0xfffff;
            else if ( !strcmp( n, "P" ) )
                saturn.p = hex( v ) & 0xf;
            else if ( !strcmp( n, "ST" ) ) {
                long st = hex( v );
                for ( int i = 0; i < 4; i++ )
                    saturn.st[ i ] = ( st >> ( 4 * i ) ) & 0xf;
            } else if ( !strcmp( n, "CARRY" ) )
                saturn.carry = hex( v ) != 0;
            else if ( !strcmp( n, "MODE" ) )
                saturn.hexmode = strcmp( v, "DEC" ) ? HEX : DEC;
            else
                fail( "unknown register", n );
        } else if ( !strcmp( cmd, "break" ) ) {
            if ( nbreaks == MAX_BREAKS )
                fail( "too many breakpoints", NULL );
            breaks[ nbreaks++ ] = hex( argv[ 1 ] );
        } else if ( !strcmp( cmd, "call" ) ) {
            saturn.rstk_ptr = 0;
            saturn.rstk[ 0 ] = SENTINEL;
            execute( hex( argv[ 1 ] ), SENTINEL, argv[ 2 ] ? hex( argv[ 2 ] ) : 10000000 );
        } else if ( !strcmp( cmd, "run" ) ) {
            execute( hex( argv[ 1 ] ), hex( argv[ 2 ] ), argv[ 3 ] ? hex( argv[ 3 ] ) : 10000000 );
        } else if ( !strcmp( cmd, "regs" ) ) {
            print_regs();
        } else if ( !strcmp( cmd, "dump" ) ) {
            Address a = hex( argv[ 1 ] );
            for ( long n = hex( argv[ 2 ] ); n > 0; n-- )
                printf( "%X", flat_fetch( a++ ) );
            printf( "\n" );
        } else {
            fail( "unknown command", cmd );
        }
        fflush( stdout );
    }
    return 0;
}
