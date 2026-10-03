# fdesign - command line IIR filter design tool
#
#   make                 build fdesign (double precision)
#   make REAL=float      build with float arithmetic, like the PIC32 firmware
#   make test            build and verify all designs against SciPy (needs Python + scipy)
#   make clean           remove build results
#
# Windows: use mingw32-make (MinGW-w64 / WinLibs) or make from MSYS2.

ifeq ($(origin CC),default)
CC = gcc
endif
REAL    ?= double
PYTHON  ?= python

ifeq ($(OS),Windows_NT)
EXE = .exe
else
EXE =
endif

TARGET  = fdesign$(EXE)
SRCS    = src/main.c src/fdesign.c lib/filter_design.c
HDRS    = src/fdesign.h lib/filter_design.h

CFLAGS  ?= -O2 -Wall -Wextra -Wno-unused-but-set-variable
CFLAGS  += -std=c99 -Ilib -Isrc -DFLD_REAL_TYPE=$(REAL)
LDLIBS  = -lm

.PHONY: all test clean

all: $(TARGET)

$(TARGET): $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) -o $@ $(SRCS) $(LDLIBS)

test: $(TARGET)
	$(PYTHON) test/verify.py ./$(TARGET)

clean:
	-rm -f $(TARGET)
