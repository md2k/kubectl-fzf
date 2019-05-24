package util

import (
	"fmt"
	"net/url"
	"os"
	"runtime/debug"
	"strconv"
	"strings"
	"time"
)

// JoinStringMap generates a list of map element separated by string excluding keys in excluded maps
func JoinStringMap(m map[string]string, exclude map[string]string, sep string) []string {
	res := make([]string, len(m))
	i := 0
	for k, v := range m {
		res[i] = fmt.Sprintf("%s%s%s", k, sep, v)
		i++
	}
	return res
}

// JoinSlicesOrNone joins a slice of string with separator or display None if there's no elements
func JoinSlicesOrNone(sl []string, sep string) string {
	if len(sl) == 0 {
		return "None"
	}
	return strings.Join(sl, sep)
}

// JoinSlicesWithMaxOrNone joins a slice of string with separator up to x elements. Display None if there's no elements
func JoinSlicesWithMaxOrNone(sl []string, max int, sep string) string {
	if len(sl) == 0 {
		return "None"
	}
	if len(sl) < max {
		return strings.Join(sl, sep)
	}
	toDisplay := sl[:max]
	toDisplay = append(toDisplay, "...")
	return strings.Join(toDisplay, sep)
}

// StringMapsEqual returns true if maps are equals
func StringMapsEqual(a map[string]string, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k := range a {
		if a[k] != b[k] {
			return false
		}
	}
	return true
}

// StringSlicesEqual returns true if slices are equals
func StringSlicesEqual(a []string, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for k := range a {
		if a[k] != b[k] {
			return false
		}
	}
	return true
}

// DumpLine replaces empty string by None, join the slice and append newline
func DumpLine(lst []string) string {
	for k, v := range lst {
		if v == "" {
			lst[k] = "None"
		}
	}
	line := strings.Join(lst, " ")
	return fmt.Sprintf("%s\n", line)
}

// ExcludeFromSlice removes elements in exclude map from slice sl
func ExcludeFromSlice(sl []string, exclude map[string]string) []string {
	res := make([]string, len(sl))
	i := 0
	for k, v := range sl {
		_, isExcluded := exclude[v]
		if isExcluded {
			continue
		}
		res[k] = v
		i++
	}
	return res[:i]
}

// FatalIf exits if the error is not nil
func FatalIf(err error) {
	if err != nil {
		debug.PrintStack()
		fmt.Printf("Fatal error: %s\n", err)
		os.Exit(-1)
	}
}

// ExtractClusterFromHost gets the cluster name from the rest configuration
func ExtractClusterFromHost(host string) (string, error) {
	parsedURL, err := url.ParseRequestURI(host)
	if err != nil {
		return "", err
	}
	res := strings.TrimPrefix(parsedURL.Host, "kubernetes.")
	return res, nil
}

// JoinIntSlice creates a string of joined int with a separator character
func JoinIntSlice(a []int, sep string) string {
	if len(a) == 0 {
		return "None"
	}
	b := make([]string, len(a))
	for i, v := range a {
		b[i] = strconv.Itoa(v)
	}
	return strings.Join(b, sep)
}

// TimeToAge converts a time to a age string
func TimeToAge(t time.Time) string {
	duration := time.Now().Sub(t)
	duration = duration.Round(time.Minute)
	if duration.Hours() > 30 {
		return fmt.Sprintf("%dd", int(duration.Hours()/24))
	}
	hour := duration / time.Hour
	duration -= hour * time.Hour
	minute := duration / time.Minute
	return fmt.Sprintf("%02d:%02d", hour, minute)
}
